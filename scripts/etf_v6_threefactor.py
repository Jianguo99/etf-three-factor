#!/usr/bin/env python3
"""
ETF国家队资金监测流水线 v6.1 — 三因子模型 + 本地SQLite数据存储
量能概率 50% + 方向概率 20% + 份额概率 30%

v5 → v6 升级：
  - 新增份额因子（sprob），权重30%，捕捉一级市场申购
  - 综合概率 cp = vp*0.5 + dp*0.2 + sp*0.3 （原 vp*0.7 + dp*0.3）
  - 份额因子基于日份额变化/20日均份额
  - 支持指定分析日期（--date YYYY-MM-DD）
  - 份额因子历史回溯：load历史份额数据，用当日vs前日的变化计算

v6 → v6.1 升级（本地数据存储）：
  - 集成 etf_data_store.py 的 SQLite 数据库 (etf_history.db)
  - 实时份额数据自动写入 DB，解决 push2 API 不可回溯问题
  - 历史分析优先查本地 DB，其次查 JSON 历史文件
  - 分析结果自动存入 DB（包含概率、信号级别等）
  - 新增 --record 参数：只采集当日数据入库，不做完整分析
  - 新增 --stats 参数：查看数据库状态

使用方式：
  python3 etf_v6_threefactor.py                # 默认：最近交易日
  python3 etf_v6_threefactor.py --date 2026-04-30  # 指定日期
  python3 etf_v6_threefactor.py --send           # 发送邮件
  python3 etf_v6_threefactor.py --record         # 仅采集份额数据入库
  python3 etf_v6_threefactor.py --stats          # 查看DB状态
"""

import json, urllib.request, ssl, os, sys, math, argparse, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta

# ---------- 本地数据存储模块 ----------
# 确保脚本所在目录在 sys.path 中（无论从哪个目录运行）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    from etf_data_store import ETFDataStore
    DATA_STORE_AVAILABLE = True
except ImportError:
    DATA_STORE_AVAILABLE = False
    print("⚠️ etf_data_store.py 未找到，本地数据存储功能不可用")

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

WORKSPACE = os.path.expanduser("~/.qclaw/workspace")
HTML_OUT = os.path.join(WORKSPACE, "ETF国家队监测-终版.html")
JSON_OUT = os.path.join(WORKSPACE, "ETF国家队监测-终版.json")
SHARES_OUT = os.path.join(WORKSPACE, "etf_shares_history.json")
THREE_FACTOR_OUT = os.path.join(WORKSPACE, "ETF三因子分析-终版.json")
THREE_FACTOR_HTML = os.path.join(WORKSPACE, "ETF三因子分析-终版.html")

EMAIL_TO = "28289062@qq.com"
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
EMAIL_FROM = "28289062@qq.com"

ETFS = {
    "510300": {"n": "华泰柏瑞沪深300ETF", "idx": "沪深300", "p": 5},
    "510310": {"n": "易方达沪深300ETF",   "idx": "沪深300", "p": 5},
    "510330": {"n": "华夏沪深300ETF",     "idx": "沪深300", "p": 5},
    "159919": {"n": "嘉实沪深300ETF",     "idx": "沪深300", "p": 4},
    "510050": {"n": "华夏上证50ETF",      "idx": "上证50",  "p": 4},
    "510500": {"n": "华泰柏瑞中证500ETF",  "idx": "中证500",  "p": 3},
    "512100": {"n": "南方中证1000ETF",    "idx": "中证1000", "p": 3},
}

PUSH2_MKT = {
    "510300": "1", "510310": "1", "510330": "1", "159919": "0",
    "510050": "1", "510500": "1", "512100": "1",
}

SPECIAL = {
    "2026-04-30": "五一前", "2026-05-06": "五一后",
}

# ============================================================
# 数据获取
# ============================================================

def fetch(code, limit=60):
    if code.startswith("sh") or code.startswith("sz"):
        pfx = code[:2]; numcode = code[2:]
    else:
        pfx = "sh" if code.startswith(("51", "56", "0")) else "sz"; numcode = code
    u = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx}{numcode},day,,,{limit},qfq"
    try:
        r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(r, timeout=15, context=ssl_ctx) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        k = d.get("data", {}).get(f"{pfx}{numcode}", {}).get("day", []) or \
            d.get("data", {}).get(f"{pfx}{numcode}", {}).get("qfqday", [])
        return [{"date": r[0], "o": float(r[1]), "c": float(r[2]),
                 "h": float(r[3]), "l": float(r[4]), "v": float(r[5])} for r in k if len(r) >= 6 and r[0]]
    except:
        return []


def fetch_fund_shares(code):
    mkt = PUSH2_MKT.get(code)
    if not mkt: return None
    url = (f"https://push2.eastmoney.com/api/qt/stock/get"
           f"?secid={mkt}.{code}&fields=f43,f57,f58,f116")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/"
        })
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
            d = json.loads(resp.read())
        data = d.get("data") or {}
        if not data: return None
        price = data.get("f43", 0) / 1000.0
        mktval_yuan = data.get("f116", 0)
        if price <= 0: return None
        shares_yi = mktval_yuan / price / 1e8
        return {"shares_yi": round(shares_yi, 2), "price": round(price, 3),
                "mktval_yi": round(mktval_yuan / 1e8, 1)}
    except Exception as e:
        print(f"  ⚠️ 份额获取失败 {code}: {e}")
        return None


def load_shares_history():
    if not os.path.exists(SHARES_OUT): return {}
    try:
        with open(SHARES_OUT, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_shares_history(history):
    dates = sorted(history.keys())
    if len(dates) > 60:
        for old in dates[:-60]:
            del history[old]
    with open(SHARES_OUT, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_historical_share(code, target_date, history):
    """从历史记录中查找目标日期的份额数据，返回 (share_yi, prev_share_yi, delta_yi, delta_pct)"""
    if target_date in history and isinstance(history[target_date], dict) and code in history[target_date]:
        target_share = history[target_date][code].get("shares_yi")
        # 找前一日
        prev_share = None
        all_dates = sorted(history.keys())
        idx = all_dates.index(target_date) if target_date in all_dates else -1
        if idx > 0:
            for prev_d in all_dates[idx-1::-1]:
                if isinstance(history.get(prev_d, {}), dict) and code in history[prev_d]:
                    prev_share = history[prev_d][code].get("shares_yi")
                    break
        if target_share and prev_share:
            delta_yi = round(target_share - prev_share, 2)
            delta_pct = round(delta_yi / prev_share * 100, 2)
            return target_share, prev_share, delta_yi, delta_pct
        elif target_share:
            return target_share, None, None, None
    return None, None, None, None


# ============================================================
# 三因子模型核心函数
# ============================================================

def vprob(r):
    """量能概率（原权重70%→现50%）"""
    if r < 0.5: return max(0, r / 0.5 * 5)
    if r < 1.0: return 5 + (r - 0.5) / 0.5 * 12
    if r < 1.3: return 17 + (r - 1) / 0.3 * 18
    if r < 1.5: return 35 + (r - 1.3) / 0.2 * 20
    if r < 2.0: return 55 + (r - 1.5) / 0.5 * 25
    if r < 3.0: return 80 + (r - 2) / 1 * 15
    if r < 5.0: return 95 + (r - 3) / 2 * 3
    return min(100, 98 + (r - 5) / 5 * 2)


def dprob(chg, t5_etf, t5_idx, vr, idx_chg):
    """方向概率（原权重30%→现20%）"""
    rally_discount = 1.0
    if idx_chg > 2.0: rally_discount = 0.60
    elif idx_chg > 1.5: rally_discount = 0.70
    elif idx_chg > 1.0: rally_discount = 0.80
    elif idx_chg > 0.5: rally_discount = 0.90

    if chg > 0.3 and t5_idx < -1:      f1 = 95
    elif chg > 0 and t5_idx < -0.5:     f1 = 85
    elif chg > 0 and t5_idx < 0:        f1 = 70
    elif abs(chg) < 0.15 and t5_idx < -1: f1 = 80
    elif abs(chg) < 0.3 and t5_idx < -0.5: f1 = 65
    elif chg > 1 and vr > 1.5 and idx_chg > 1: f1 = 25
    elif chg > 1 and vr > 1.5:          f1 = 45
    elif chg > 0.5 and vr > 1.3 and idx_chg > 1: f1 = 35
    elif chg > 0.5 and vr > 1.3:        f1 = 50
    elif chg > 0:                       f1 = 40
    elif chg < -1.5 and vr > 2:         f1 = 8
    elif chg < -0.5 and vr > 1.5:       f1 = 15
    else:                               f1 = 25

    gap = t5_etf - t5_idx
    if gap > 3:      f2 = 95
    elif gap > 2:    f2 = 85
    elif gap > 1.2:  f2 = 75
    elif gap > 0.6:  f2 = 60
    elif gap > 0.2:  f2 = 50
    elif gap > -0.2: f2 = 40
    elif gap > -0.6: f2 = 30
    else:            f2 = 15

    if t5_idx < -4:     f3 = 95
    elif t5_idx < -3:   f3 = 90
    elif t5_idx < -2:   f3 = 80
    elif t5_idx < -1:   f3 = 70
    elif t5_idx < -0.5: f3 = 55
    elif t5_idx < 0:    f3 = 45
    elif t5_idx < 1:    f3 = 35
    elif t5_idx < 3:    f3 = 20
    else:               f3 = 10
    f4 = 35

    raw = f1 * 0.4 + f2 * 0.3 + f3 * 0.2 + f4 * 0.1
    return round(raw * rally_discount, 1)


def sprob(share_delta_pct):
    """
    份额概率（权重30%）【v6新增】
    基于日份额变化 / 20日均份额（近似用日变化比）
    
    份额变动比 → 份额概率：
      >10% → 95%  |  >5% → 80%  |  >3% → 65%  |  >1% → 45%
      0-1% → 30%  |  < -1% → 15% |  < -5% → 5%  
    """
    if share_delta_pct is None:
        return None  # 数据不可用
    ap = abs(share_delta_pct)
    if share_delta_pct > 10:   return 95
    elif share_delta_pct > 5:  return 80 + (share_delta_pct - 5) / 5 * 15
    elif share_delta_pct > 3:  return 65 + (share_delta_pct - 3) / 2 * 15
    elif share_delta_pct > 1:  return 45 + (share_delta_pct - 1) / 2 * 20
    elif share_delta_pct > 0:  return 30 + share_delta_pct / 1 * 15
    elif share_delta_pct > -1:  return 15 + (share_delta_pct + 1) / 1 * 15
    elif share_delta_pct > -5:  return 5 + (share_delta_pct + 5) / 4 * 10
    else:                       return max(0, 5 + (share_delta_pct + 5) / 5 * 5)


def analyze_all(data, idx_d, shares_map, target_date, days=35):
    """
    三因子模型分析
    shares_map: {code: {date: {shares_yi, prev_shares_yi, delta_yi, delta_pct}}}
    """
    if len(data) < 22: return []
    res = []
    aligned = align_idx(data, idx_d)
    for i in range(max(21, len(data) - days), len(data)):
        d = data[i]
        v = d["v"] / 10000
        pv = [data[j]["v"] / 10000 for j in range(i - 20, i)]
        ma = sum(pv) / 20
        if ma == 0: continue
        vr = v / ma
        pc = data[i - 1]["c"]
        chg = (d["c"] - pc) / pc * 100 if pc > 0 else 0
        t5 = i >= 6 and data[i - 5]["c"] > 0 and (d["c"] - data[i - 5]["c"]) / data[i - 5]["c"] * 100 or 0
        t5i = t5
        idchg = 0
        if i < len(aligned) and aligned[i] is not None:
            ii = aligned[i]
            vp_idx = ii > 0 and idx_d[ii - 1]["c"] > 0 and (idx_d[ii]["c"] - idx_d[ii - 1]["c"]) / idx_d[ii - 1]["c"] * 100 or 0
            idchg = round(vp_idx, 1)
            if i >= 6 and aligned[i - 5] is not None:
                j5 = aligned[i - 5]
                t5i = idx_d[j5]["c"] > 0 and (idx_d[ii]["c"] - idx_d[j5]["c"]) / idx_d[j5]["c"] * 100 or 0
        vp = vprob(vr)
        dp = dprob(chg, t5, round(t5i, 2), vr, idchg)

        # 三因子：份额概率
        code_key = None
        for ck in shares_map:
            if d["date"] in shares_map[ck]:
                code_key = ck
                break
        sp = None
        share_delta_pct = None
        share_delta_yi = None
        if code_key and d["date"] in shares_map[code_key]:
            info = shares_map[code_key][d["date"]]
            share_delta_pct = info.get("delta_pct")
            share_delta_yi = info.get("delta_yi")
            sp = sprob(share_delta_pct)

        # 三因子综合概率
        if sp is not None:
            cp = round(vp * 0.5 + dp * 0.2 + sp * 0.3, 1)
        else:
            # 份额数据不可用，退化为二因子（保持70/30用于对比）
            cp = round(vp * 0.7 + dp * 0.3, 1)

        tag = SPECIAL.get(d["date"], "")
        res.append({
            "d": d["date"], "c": d["c"], "chg": round(chg, 2),
            "t5": round(t5, 2), "t5i": round(t5i, 2), "idx_chg": idchg,
            "v": round(v, 2), "vma": round(ma, 2), "vr": round(vr, 2),
            "vp": round(vp, 1), "dp": dp, "sp": sp, "cp": cp,
            "share_delta_pct": share_delta_pct, "share_delta_yi": share_delta_yi,
            "tag": tag, "has_shares": sp is not None,
        })
    return res


def align_idx(data, idx_d):
    idx_map = {}
    for j, d in enumerate(idx_d):
        idx_map[d["date"]] = j
    return [idx_map.get(d["date"]) for d in data]


# ============================================================
# HTML 报告生成（三因子版）
# ============================================================

def gen_html(all_hist, latest_map, idx_300_data, shares_data, target_date):
    dates = set()
    for hh in all_hist.values():
        for h in hh:
            dates.add(h["d"])
    dates = sorted(dates)
    primary_date = target_date if target_date in dates else dates[-1]

    primary = {}
    high_codes = []
    mid_codes = []
    for code, hist in all_hist.items():
        for h in hist:
            if h["d"] == primary_date:
                primary[code] = h
                if h["cp"] >= 70: high_codes.append(code)
                elif h["cp"] >= 50: mid_codes.append(code)
                break

    hs300_codes = [c for c in ETFS if ETFS[c]["idx"] == "沪深300"]
    hs300_alerts = sum(1 for c in hs300_codes if c in primary and primary[c]["cp"] >= 50)
    total_high = len(high_codes)
    total_mid = len(mid_codes)

    idx_300_hist = {}
    if idx_300_data:
        for d in idx_300_data:
            idx_300_hist[d["date"]] = d
    idx_gain = 0
    if primary_date in idx_300_hist:
        pd = idx_300_hist[primary_date]
        prev_d = dates.index(primary_date) > 0 and dates[dates.index(primary_date) - 1]
        if prev_d and prev_d in idx_300_hist:
            pp = idx_300_hist[prev_d]
            idx_gain = round((pd["c"] - pp["c"]) / pp["c"] * 100, 2)

    avg_dp = 0
    dp_count = 0
    for code in primary:
        avg_dp += primary[code]["dp"]
        dp_count += 1
    avg_dp = avg_dp / dp_count if dp_count > 0 else 0

    # 份额数据汇总
    net_purchase_total = 0
    net_redempt_total = 0
    shares_available_count = 0
    for code, sd in shares_data.items():
        d = sd.get("delta_yi")
        if d is not None:
            if d > 0: net_purchase_total += d
            else: net_redempt_total += abs(d)
            shares_available_count += 1

    # 三因子模型标识
    threef_tag = "三因子: 量能50%+方向20%+份额30%"
    if shares_available_count == 0:
        threef_tag += " (份额数据不可回溯，退化为二因子70/30)"

    # 综合判断
    if total_high >= 2 and hs300_alerts >= 3:
        if idx_gain > 1.0 and avg_dp < 40:
            verdict = f"⚠️ 多ETF放量高确信({total_high}只)，但{primary_date}大盘涨{idx_gain:+.2f}%。普涨环境下放量未必国家队专属。{threef_tag}。份额端：{'+' if net_purchase_total > net_redempt_total else ''}{net_purchase_total:.1f}亿净申购/{net_redempt_total:.1f}亿净赎回。"
            vcls = "warn"
        elif idx_gain > 1.5:
            verdict = f"⚠️ 多ETF放量高确信，但{primary_date}大盘涨{idx_gain:+.2f}%。{threef_tag}。份额端：{'+' if net_purchase_total > net_redempt_total else ''}{net_purchase_total:.1f}亿净申购/{net_redempt_total:.1f}亿净赎回。"
            vcls = "warn"
        else:
            verdict = f"🔥 {total_high}只ETF高确信·{hs300_alerts}/4沪深300同步。{threef_tag}。份额端：{'+' if net_purchase_total > net_redempt_total else ''}{net_purchase_total:.1f}亿净申购/{net_redempt_total:.1f}亿净赎回。"
            vcls = "warn"
    elif total_high >= 1:
        verdict = f"⚠️ 部分ETF触发高确信（{', '.join(ETFS[c]['n'][:6] for c in high_codes)}等）。{threef_tag}。份额端：{'+' if net_purchase_total > net_redempt_total else ''}{net_purchase_total:.1f}亿净申购/{net_redempt_total:.1f}亿净赎回。"
        vcls = "warn"
    elif total_mid >= 2:
        verdict = f"📊 {total_mid}只中等信号。{threef_tag}。份额端：{'+' if net_purchase_total > net_redempt_total else ''}{net_purchase_total:.1f}亿净申购/{net_redempt_total:.1f}亿净赎回。"
        vcls = "mid"
    else:
        verdict = f"✅ {primary_date} 全市场正常。{threef_tag}。"
        if shares_available_count == 0:
            verdict += " 份额数据不可回溯"

    # 15日信号趋势
    date_score = {}
    for code, hist in all_hist.items():
        for h in hist:
            d = h["d"]
            if d not in date_score:
                date_score[d] = {"cnt": 0, "high": 0, "mid": 0, "avg": 0}
            date_score[d]["cnt"] += 1
            date_score[d]["avg"] += h["cp"]
            if h["cp"] >= 70: date_score[d]["high"] += 1
            elif h["cp"] >= 50: date_score[d]["mid"] += 1
    for d in date_score:
        date_score[d]["avg"] = round(date_score[d]["avg"] / date_score[d]["cnt"], 1)
    date_score[d]["total"] = date_score[d]["high"] * 2 + date_score[d]["mid"]

    trend_dates = sorted(date_score.keys())[-15:]
    bars = ""
    for d in trend_dates:
        ds = date_score[d]
        h = min(42, max(3, ds["avg"] * 0.55))
        if ds["high"] >= 2: cls = "bar-hi"
        elif ds["high"] + ds["mid"] >= 2: cls = "bar-md"
        elif ds["mid"] >= 2: cls = "bar-md"
        else: cls = "bar-lo"
        tag = SPECIAL.get(d, "")
        tl = f"{d} {tag}" if tag else d
        bars += f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:3px"><div class="bar {cls}" style="height:{h}px" title="{tl}: {ds["high"]}高+{ds["mid"]}中 CP均{ds["avg"]:.0f}%"></div><span style="font-size:8px;color:#4a5568">{d[5:]}</span></div>'

    # ETF表格行
    rows = ""
    for code, info in ETFS.items():
        p = primary.get(code)
        sd = shares_data.get(code, {})
        cp = p["cp"] if p else 0
        if cp >= 70:
            cls = "tr-hi"; sc = "#ef4444"; si = "🔴"
        elif cp >= 50:
            cls = "tr-md"; sc = "#f59e0b"; si = "🟡"
        else:
            cls = ""; sc = "#22c55e"; si = "🟢"

        chg = p["chg"] if p else 0
        chc = "#ef4444" if chg > 0 else ("#22c55e" if chg < 0 else "#94a3b8")
        tag_html = f'<span style="font-size:8px;background:rgba(239,68,68,0.15);color:#fca5a5;padding:1px 4px;border-radius:2px;margin-left:4px">{p["tag"]}</span>' if (p and p.get("tag")) else ""

        # 份额列
        sh_html = ""
        if sd:
            sh_yi = sd.get("shares_yi", "-")
            d_yi = sd.get("delta_yi")
            d_pct = sd.get("delta_pct")
            if d_yi is not None:
                dc = "#22c55e" if d_yi > 0 else ("#ef4444" if d_yi < 0 else "#94a3b8")
                arrow = "↑" if d_yi > 0 else ("↓" if d_yi < 0 else "→")
                sh_html = f'<td style="color:#94a3b8">{sh_yi:.1f}亿</td><td style="font-weight:600;color:{dc}">{arrow}{abs(d_yi):.1f}亿({d_pct:+.2f}%)</td>'
            else:
                sh_html = f'<td style="color:#94a3b8">{sh_yi}亿</td><td style="color:#64748b">-</td>'
        else:
            sh_html = '<td style="color:#64748b">-</td><td style="color:#64748b">-</td>'

        # 份额概率列（新增）
        sp_val = p["sp"] if p and p.get("has_shares") else "-"
        sp_col = "#94a3b8"
        if isinstance(sp_val, (int, float)):
            sp_col = "#ef4444" if sp_val >= 70 else ("#f59e0b" if sp_val >= 50 else "#22c55e")
            sp_display = f'{sp_val:.0f}%'
        else:
            sp_display = "-"

        # 模型标识
        model_note = "三因子" if (p and p.get("has_shares")) else "二因子"

        rows += f'''<tr class="{cls}">
  <td style="white-space:nowrap">{si} <b>{info["n"]}</b></td>
  <td style="color:#64748b">{code}</td>
  <td style="color:{chc}">{chg:+.2f}%</td>
  <td>{p["v"]:.0f}万</td>
  <td>{p["vma"]:.0f}万</td>
  <td style="font-weight:600;color:#cbd5e1">{p["vr"]:.2f}x</td>{sh_html}
  <td style="color:#94a3b8">{p["vp"]:.0f}%</td>
  <td style="color:#94a3b8">{p["dp"]:.0f}%</td>
  <td style="color:{sp_col}">{sp_display}</td>
  <td style="font-weight:700;font-size:13px;color:{sc};white-space:nowrap">{cp:.0f}%{tag_html}</td>
</tr>'''

    # 信号列表
    signal_dates = [(d, v) for d, v in date_score.items() if v["high"] + v["mid"] >= 3]
    signal_dates.sort(key=lambda x: x[0], reverse=True)
    sig_list = ""
    for d, v in signal_dates[:8]:
        tag = SPECIAL.get(d, "")
        dots = '<div class="sig-dots">'
        dots += '<div class="sig-dot hi"></div>' * v["high"]
        dots += '<div class="sig-dot md"></div>' * v["mid"]
        dots += '</div>'
        tag_html = f'<span class="sig-tag">{tag}</span>' if tag else ""
        cnt = f'🔥{v["high"]} 🟡{v["mid"]} CP{v["avg"]:.0f}%'
        sig_list += f'<div class="sig-row"><span class="sig-date">{d[5:]}</span>{tag_html}{dots}<span class="sig-cnt">{cnt}</span></div>'

    # 份额概览
    total_shares = sum((shares_data.get(c, {}).get("shares_yi") or 0) for c in ETFS)
    total_delta = sum((shares_data.get(c, {}).get("delta_yi") or 0) for c in ETFS)
    delta_cls = "#22c55e" if total_delta > 0 else ("#ef4444" if total_delta < 0 else "#94a3b8")
    delta_arrow = "↑" if total_delta > 0 else ("↓" if total_delta < 0 else "→")

    # 模型切换说明
    model_desc = "三因子模型: 量能P×50% + 方向P×20% + 份额P×30%"
    if shares_available_count == 0:
        model_desc += " (份额数据不可回溯，当前退化为二因子70/30)"

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=1440,initial-scale=1">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html{{display:flex;justify-content:center;align-items:center;min-height:100vh;background:#0a0f1a}}
body{{width:1440px;height:810px;overflow:hidden;font-family:-apple-system,"SF Pro Display","PingFang SC","Microsoft YaHei",sans-serif;background:#111c2e;color:#dfe6ef;display:flex;flex-direction:column;border-radius:12px;box-shadow:0 0 80px rgba(56,189,248,0.04)}}
body::before{{content:'';position:absolute;inset:0;background-image:radial-gradient(rgba(148,163,184,0.03) 1px,transparent 1px);background-size:28px 28px;pointer-events:none;z-index:0}}
.hdr{{padding:8px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(56,189,248,0.12);flex-shrink:0;position:relative;z-index:1;background:rgba(17,28,46,0.7);backdrop-filter:blur(8px)}}
.hdr-left{{display:flex;align-items:baseline;gap:14px}}
.hdr h1{{font-size:18px;font-weight:700;color:#f1f5f9;letter-spacing:-0.3px}}
.hdr .sub{{font-size:12px;color:#8896ab}}
.hdr .meta{{font-size:11px;color:#7a8ba0;text-align:right;line-height:1.6}}
.hdr .meta .dot{{display:inline-block;width:6px;height:6px;border-radius:50%;background:#22c55e;margin-right:5px;box-shadow:0 0 6px rgba(34,197,94,0.5)}}
.banner{{margin:6px 22px 0;padding:6px 16px;border-radius:8px;font-size:12px;line-height:1.45;flex-shrink:0;position:relative;z-index:1;display:flex;align-items:flex-start;gap:8px}}
.banner.warn{{background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.18);color:#fca5a5}}
.banner.mid{{background:rgba(245,158,11,0.05);border:1px solid rgba(245,158,11,0.15);color:#fcd34d}}
.banner.ok{{background:rgba(34,197,94,0.04);border:1px solid rgba(34,197,94,0.12);color:#86efac}}
.banner .ico{{font-size:18px;flex-shrink:0;margin-top:1px}}
.banner b{{color:#e8edf5}}
.stats{{display:flex;gap:10px;padding:6px 22px 4px;flex-shrink:0;position:relative;z-index:1}}
.stat{{flex:1;background:rgba(24,36,56,0.5);border:1px solid rgba(56,189,248,0.1);border-radius:8px;padding:10px 14px;display:flex;align-items:center;gap:10px}}
.stat .vi{{font-size:26px;font-weight:900;line-height:1}}
.stat .tx{{font-size:11px;color:#8896ab;line-height:1.3}}
.stat .tx span{{display:block;font-size:12px;color:#dfe6ef;font-weight:600}}
.main{{display:flex;flex:1;padding:8px 22px 6px;gap:14px;overflow:hidden;position:relative;z-index:1;align-items:stretch}}
.tbl-wrap{{flex:1;min-width:0;overflow:hidden;background:rgba(20,32,50,0.4);border-radius:8px;border:1px solid rgba(56,189,248,0.08);display:flex;flex-direction:column}}
.tbl-wrap table{{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed}}
.tbl-wrap thead th{{text-align:left;padding:5px 6px;font-weight:600;color:#7a8ba0;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid rgba(56,189,248,0.1);white-space:nowrap;background:rgba(18,28,44,0.4)}}
.tbl-wrap td{{padding:12px 6px;border-bottom:1px solid rgba(20,30,50,0.5);color:#b0bdd0;transition:background 0.15s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tbl-wrap tbody tr:hover td{{background:rgba(56,189,248,0.03)}}
.tbl-wrap tr.tr-hi td{{background:rgba(239,68,68,0.05)}}
.tbl-wrap tr.tr-hi:hover td{{background:rgba(239,68,68,0.08)}}
.tbl-wrap tr.tr-md td{{background:rgba(245,158,11,0.03)}}
.tbl-wrap tr.tr-md:hover td{{background:rgba(245,158,11,0.06)}}
.tbl-wrap .tnote{{font-size:10px;color:#64748b;padding:6px 10px;border-top:1px solid rgba(56,189,248,0.08);margin-top:auto}}
.rp{{width:380px;display:flex;flex-direction:column;gap:10px;overflow:hidden;flex-shrink:0;align-self:stretch}}
.rp .card{{background:rgba(22,34,52,0.45);border:1px solid rgba(56,189,248,0.08);border-radius:8px;overflow:hidden}}
.rp .card:last-child{{flex:1;display:flex;flex-direction:column}}
.rp .card .ttl{{font-size:11px;font-weight:600;color:#8b9bb5;padding:8px 10px 6px;display:flex;align-items:center;gap:6px}}
.rp .card .ttl::before{{content:'';width:3px;height:12px;background:linear-gradient(180deg,#38bdf8,#818cf8);border-radius:2px}}
.rp .trend{{display:flex;align-items:flex-end;gap:2px;height:44px;padding:4px 10px 8px}}
.rp .trend .bar{{flex:1;border-radius:2px 2px 0 0;min-width:4px}}
.rp .trend .bar-hi{{background:linear-gradient(180deg,#ef4444aa,#ef444444)}}
.rp .trend .bar-md{{background:linear-gradient(180deg,#f59e0baa,#f59e0b44)}}
.rp .trend .bar-lo{{background:linear-gradient(180deg,#334155,#1a2234)}}
.rp .sig{{padding:6px 12px 8px;display:flex;flex-direction:column;gap:5px;flex:1;overflow-y:auto}}
.rp .sig-row{{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:6px;background:rgba(20,30,50,0.4)}}
.rp .sig-date{{font-size:12px;font-weight:600;color:#dfe6ef;min-width:60px}}
.rp .sig-tag{{font-size:9px;background:rgba(56,189,248,0.1);color:#7dd3fc;padding:1px 6px;border-radius:3px}}
.rp .sig-dots{{display:flex;gap:3px;flex:1}}
.rp .sig-dot{{width:7px;height:7px;border-radius:50%}}
.rp .sig-dot.hi{{background:#ef4444;box-shadow:0 0 4px rgba(239,68,68,0.4)}}
.rp .sig-dot.md{{background:#f59e0b;box-shadow:0 0 4px rgba(245,158,11,0.3)}}
.rp .sig-cnt{{font-size:11px;color:#8896ab;white-space:nowrap}}
.ftr{{padding:8px 24px;font-size:11px;color:#64748b;border-top:1px solid rgba(56,189,248,0.1);flex-shrink:0;display:flex;justify-content:center;align-items:center;gap:6px;position:relative;z-index:1}}
.ftr span{{color:#7a8ba0}}
</style></head><body>

<div class="hdr">
  <div class="hdr-left">
    <h1>ETF三因子监测报告</h1>
    <span class="sub">{model_desc}</span>
  </div>
  <div class="meta">
    <div><span class="dot"></span>分析日: {primary_date}</div>
    <div>{datetime.now().strftime("%Y-%m-%d %H:%M")} · v6</div>
  </div>
</div>

<div class="banner {'warn' if total_high>=2 else 'mid' if total_high>=1 or total_mid>=2 else 'ok'}">
  <span class="ico">{'🔥' if total_high>=2 else '⚠️' if total_high>=1 or total_mid>=2 else '✅'}</span>
  <div>📋 <b>综合判断：</b>{verdict}</div>
</div>

<div class="stats">
  <div class="stat">
    <div class="vi" style="color:{'#ef4444' if total_high>0 else '#f59e0b' if total_mid>0 else '#22c55e'}">{total_high}</div>
    <div class="tx"><span>高确信</span>🔴 触发警报</div>
  </div>
  <div class="stat">
    <div class="vi" style="color:{'#f59e0b' if total_mid>0 else '#4a5568'}">{total_mid}</div>
    <div class="tx"><span>中等关注</span>🟡 需跟踪</div>
  </div>
  <div class="stat">
    <div class="vi" style="color:{'#ef4444' if hs300_alerts>=3 else '#f59e0b' if hs300_alerts>=2 else '#22c55e'}">{hs300_alerts}/4</div>
    <div class="tx"><span>沪深300</span>一致性</div>
  </div>
  <div class="stat">
    <div class="vi" style="color:{delta_cls}">{delta_arrow}{abs(total_delta):.1f}</div>
    <div class="tx"><span>份额日变</span>亿份 · 净申赎</div>
  </div>
  <div class="stat">
    <div class="vi" style="color:#818cf8">{shares_available_count}/7</div>
    <div class="tx"><span>份额覆盖</span>三因子完整度</div>
  </div>
</div>

<div class="main">
  <div class="tbl-wrap">
    <table>
    <thead><tr>
      <th style="width:20%">ETF名称</th>
      <th style="width:7%">代码</th>
      <th style="width:6%">涨跌</th>
      <th style="width:8%">成交量</th>
      <th style="width:8%">20日均</th>
      <th style="width:6%">倍量</th>
      <th style="width:7%">份额</th>
      <th style="width:8%">份额日变</th>
      <th style="width:6%">量能P</th>
      <th style="width:6%">方向P</th>
      <th style="width:6%">份额P</th>
      <th style="width:6%">综合</th>
    </tr></thead>
    <tbody>{rows}
    </tbody>
    </table>
    <div class="tnote">
      ⚡ {model_desc} · 含普涨折扣 · 份额数据来源东方财富push2 · 份额P=份额日变化/前日份额
    </div>
  </div>

  <div class="rp">
    <div class="card">
      <div class="ttl">📈 15日信号趋势（综合概率）</div>
      <div class="trend">{bars}</div>
    </div>
    <div class="card">
      <div class="ttl">📅 30日同步信号</div>
      <div class="sig">{sig_list}</div>
    </div>
  </div>
</div>

<div class="ftr">
  <span>ETF国家队资金监测 · 三因子模型 v6 · 腾讯财经API + 东方财富push2 · 小贺FIRE了</span>
</div>

</body></html>'''


# ============================================================
# 邮件发送
# ============================================================

def send_email(html_path, json_path, target_date):
    password = os.environ.get("QQMAIL_AUTH_CODE") or os.environ.get("SMTP_PASS")
    if not password:
        print("⚠️ 未设置 QQMAIL_AUTH_CODE 或 SMTP_PASS 环境变量，跳过邮件发送")
        return False

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = f"ETF三因子分析报告 - {target_date} - v6"

    body = f"📊 ETF三因子监测报告（v6）\n\n分析日期: {target_date}\n模型: 量能50% + 方向20% + 份额30%\n\n报告详见附件。\n\n---\n此邮件由ETF三因子监测系统自动发送 · 小贺FIRE了"
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for fpath, fname in [(html_path, f"ETF三因子-{target_date}.html"),
                           (json_path, f"ETF三因子-{target_date}.json")]:
        if os.path.exists(fpath):
            with open(fpath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={fname}")
                msg.attach(part)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(EMAIL_FROM, password)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"✅ 邮件已发送至 {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False


# ============================================================
# 主程序
# ============================================================

def record_shares_only():
    """仅采集当日份额数据到本地DB（不跑完整分析）"""
    if not DATA_STORE_AVAILABLE:
        print("❌ etf_data_store 不可用")
        return
    store = ETFDataStore()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"📊 采集 {today} 的ETF份额数据...")
    for code, info in ETFS.items():
        print(f"  📊 {code} {info['n']}...", end=" ")
        sh_data = fetch_fund_shares(code)
        if sh_data:
            store.upsert_record(today, code, {
                "date": today, "code": code,
                "name": info["n"], "idx_name": info["idx"],
                "shares_yi": sh_data.get("shares_yi"),
            })
            print(f"✅ {sh_data['shares_yi']:.1f}亿份")
        else:
            print("❌ 获取失败")
    stats = store.get_stats()
    print(f"\n📊 数据库状态: {stats['total_records']}条记录, {stats['total_dates']}个交易日")
    print(f"   日期范围: {stats['date_range'][0]} ~ {stats['date_range'][1]}")
    print(f"   含份额: {stats['records_with_shares']}条")


def main(target_date=None, do_send=False, record_only=False):
    # 初始化 DB
    store = ETFDataStore() if DATA_STORE_AVAILABLE else None

    if record_only:
        record_shares_only()
        return

    print("=" * 70)
    print("🛡️ ETF国家队资金监测 v6.1 — 三因子模型 + 本地DB")
    print(f"   量能50% + 方向20% + 份额30%")
    if store:
        db_stats = store.get_stats()
        print(f"   📦 本地DB: {db_stats['total_records']}条 / {db_stats['total_dates']}日")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # 1. 获取沪深300指数数据
    print("\n📊 Step 1: 获取沪深300指数数据...")
    idx_300 = fetch("sh000300", 60)
    if idx_300:
        print(f"  ✅ {len(idx_300)}条  {idx_300[-1]['date']}~{idx_300[0]['date']}")

    # 2. 加载历史份额数据（优先从本地DB，其次JSON文件）
    print("\n📊 Step 2: 加载历史份额数据...")
    shares_history = load_shares_history()
    print(f"  📦 JSON历史: {len(shares_history)}日")

    # 同时获取实时份额（push2 API）并写入本地DB
    if store and not target_date:
        # 实时运行：采集份额数据
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"  📡 采集 {today_str} 实时份额数据...")
        for code, info in ETFS.items():
            sh_data = fetch_fund_shares(code)
            if sh_data:
                store.upsert_record(today_str, code, {
                    "date": today_str, "code": code,
                    "name": info["n"], "idx_name": info["idx"],
                    "shares_yi": sh_data.get("shares_yi"),
                })
                # 也记录到 JSON（保持兼容）
                if today_str not in shares_history:
                    shares_history[today_str] = {}
                shares_history[today_str][code] = {"shares_yi": sh_data["shares_yi"], "ts": datetime.now().isoformat()}
                print(f"    ✅ {code} {info['n'][:12]}: {sh_data['shares_yi']:.1f}亿份")
        save_shares_history(shares_history)
    elif store and target_date:
        db_shares = store.get_range(start_date=target_date, end_date=target_date)
        if db_shares:
            print(f"  📦 本地DB有{target_date}的份额记录 ({len(db_shares)}条)")
        else:
            print(f"  ⚠️ 本地DB无{target_date}份额记录，退化为二因子")
    print(f"  📊 累计历史: {len(shares_history)}日")

    # 3. 构建份额映射
    shares_map = {}
    for code in ETFS:
        shares_map[code] = {}
        for date, entries in shares_history.items():
            if isinstance(entries, dict) and code in entries:
                target_sh, prev_sh, delta_yi, delta_pct = get_historical_share(code, date, shares_history)
                shares_map[code][date] = {
                    "shares_yi": entries[code].get("shares_yi"),
                    "delta_yi": delta_yi,
                    "delta_pct": delta_pct,
                }

    # 4. 获取ETF行情 + 三因子分析
    print("\n📊 Step 3: 获取ETF行情 + 三因子分析...")
    if target_date:
        print(f"  🎯 目标分析日期: {target_date}")

    all_hist = {}
    latest_map = {}
    target_shares_data = {}

    for code, info in ETFS.items():
        print(f"\n  📊 {code} {info['n']} ({info['idx']})")
        data = fetch(code, 60)
        if not data:
            print("    ❌ 数据获取失败")
            continue
        if len(data) < 22:
            print(f"    ⚠️ 仅{len(data)}条，不足22条")
            continue

        hist = analyze_all(data, idx_300, shares_map, target_date or "", 35)
        if not hist:
            print("    ⚠️ 分析失败")
            continue

        all_hist[code] = hist

        # 找到目标日期的分析结果
        target_hist = None
        if target_date:
            for h in hist:
                if h["d"] == target_date:
                    target_hist = h
                    break
        if not target_hist:
            target_hist = hist[-1]

        l = target_hist

        # 获取份额数据（目标日期）
        sh_on_target = shares_map.get(code, {}).get(target_date or l["d"], {})
        target_shares_data[code] = sh_on_target

        latest_map[code] = {
            "d": l["d"], "c": l["c"], "chg": l["chg"], "cp": l["cp"],
            "vr": l["vr"], "vp": l["vp"], "dp": l["dp"], "sp": l["sp"],
            "v": l["v"], "vma": l["vma"],
            "shares_yi": sh_on_target.get("shares_yi"),
            "delta_yi": sh_on_target.get("delta_yi"),
            "delta_pct": sh_on_target.get("delta_pct"),
        }

        sp_str = f"份额P:{l['sp']:.0f}%" if l.get("has_shares") else "份额P:N/A"
        s = "🔥" if l["cp"] >= 70 else ("⚠️" if l["cp"] >= 50 else "○")
        model_flag = "三因子" if l.get("has_shares") else "二因子"
        t = f"[{l['tag']}]" if l.get("tag") else ""
        print(f"    {s} {l['d']} {t} | {l['chg']:+.2f}% | {l['v']:.0f}万({l['vr']:.2f}x) | 量能P:{l['vp']:.0f}% 方向P:{l['dp']:.0f}% {sp_str} → CP:{l['cp']:.0f}% [{model_flag}]")

    # 5. 重要信号回溯 (生成 actual_date)
    print("\n" + "=" * 70)
    print("📋 30日重要信号回溯（三因子模型）")
    print("=" * 70)
    date_sig = {}
    for code, hist in all_hist.items():
        for h in hist:
            d = h["d"]
            if d not in date_sig:
                date_sig[d] = {"total": 0, "high": 0, "mid": 0, "codes": []}
            date_sig[d]["total"] += 1
            if h["cp"] >= 70: date_sig[d]["high"] += 1; date_sig[d]["codes"].append(f"{code}({h['cp']:.0f}%)")
            elif h["cp"] >= 50: date_sig[d]["mid"] += 1
    sigs = [(d, v) for d, v in date_sig.items() if v["high"] >= 2 or v["high"] + v["mid"] >= 4]
    sigs.sort(key=lambda x: x[0], reverse=True)
    if sigs:
        for d, v in sigs[:10]:
            t = SPECIAL.get(d, "")
            ts = f" [{t}]" if t else ""
            print(f"  📅 {d}{ts}: {v['high']}🔴+{v['mid']}🟡 → {', '.join(v['codes'][:5])}")
    else:
        print("  ℹ️ 无多ETF同步信号")

    actual_date = target_date if target_date else list(date_sig.keys())[-1]

    # 计算当日沪深300涨跌（用于DB记录）
    idx_gain = 0
    if idx_300 and len(idx_300) >= 2:
        idx_today = None
        for d in idx_300:
            if d["date"] == actual_date:
                idx_today = d
                break
        if idx_today:
            prev_idx = None
            for d in idx_300:
                if d["date"] < actual_date:
                    prev_idx = d
                    break
            if prev_idx and prev_idx.get("c"):
                idx_gain = round((idx_today["c"] - prev_idx["c"]) / prev_idx["c"] * 100, 2)

    # 6. 记录分析结果到本地DB
    if store:
        print(f"\n💾 Step 6: 保存分析结果到本地DB...")
        etf_results_for_db = {}
        for code, hist in all_hist.items():
            for h in hist:
                if h["d"] == actual_date:
                    sh = target_shares_data.get(code, {})
                    etf_results_for_db[code] = {
                        "name": ETFS[code]["n"], "idx_name": ETFS[code]["idx"],
                        "c": h["c"], "chg": h["chg"],
                        "v": h["v"], "vma": h["vma"], "vr": h["vr"],
                        "vp": h["vp"], "dp": h["dp"], "sp": h["sp"], "cp": h["cp"],
                        "shares_yi": sh.get("shares_yi"),
                        "delta_yi": sh.get("delta_yi"),
                        "delta_pct": sh.get("delta_pct"),
                    }
                    break
        cnt = store.record_from_v6_result(actual_date, etf_results_for_db, idx_gain)
        print(f"  ✅ 已记录 {cnt}条数据到本地DB")
        db_stats = store.get_stats()
        print(f"  📦 DB总量: {db_stats['total_records']}条 / {db_stats['total_dates']}日 / 含份额{db_stats['records_with_shares']}条")
    else:
        print(f"\n💾 本地DB不可用，跳过数据持久化")

    # 7. 生成HTML (原step 6)
    print(f"\n🎨 Step 7: 生成三因子HTML报告 (分析日: {actual_date})...")
    html = gen_html(all_hist, latest_map, idx_300, target_shares_data, target_date or "")
    with open(THREE_FACTOR_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ {THREE_FACTOR_HTML} ({len(html)} bytes)")

    # 8. 保存JSON (原step 7)
    with open(THREE_FACTOR_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "run_time": datetime.now().isoformat(),
            "model": "三因子: 量能50%+方向20%+份额30%",
            "target_date": actual_date,
            "signal_dates": [(d, v["high"], v["mid"], v["codes"][:4]) for d, v in sigs[:10]],
            "latest": latest_map,
            "shares_data": target_shares_data,
        }, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {THREE_FACTOR_OUT}")

    # 9. 发送邮件 (原step 8)
    if do_send:
        print(f"\n📧 Step 8: 发送邮件到 {EMAIL_TO}...")
        send_email(THREE_FACTOR_HTML, THREE_FACTOR_OUT, actual_date)
    else:
        print(f"\n📧 跳过邮件发送 (使用 --send 启用)")

    return html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETF三因子监测 v6.1")
    parser.add_argument("--date", type=str, default=None,
                        help="分析日期 (YYYY-MM-DD)，默认最近交易日")
    parser.add_argument("--send", action="store_true",
                        help="发送邮件")
    parser.add_argument("--record", action="store_true",
                        help="仅采集当日份额数据入库，不做完整分析")
    parser.add_argument("--stats", action="store_true",
                        help="查看本地DB状态，不做分析")
    args = parser.parse_args()

    if args.stats:
        if not DATA_STORE_AVAILABLE:
            print("❌ etf_data_store.py 不可用")
            sys.exit(1)
        store = ETFDataStore()
        stats = store.get_stats()
        print("=" * 60)
        print("📊 ETF本地数据库状态")
        print("=" * 60)
        print(f"  数据库路径: {store.db_path}")
        print(f"  总记录数:   {stats['total_records']}")
        print(f"  覆盖交易日: {stats['total_dates']}")
        print(f"  日期范围:   {stats['date_range'][0]} ~ {stats['date_range'][1]}")
        print(f"  含份额记录: {stats['records_with_shares']}/{stats['total_records']}")
        print(f"\n  最近5个交易日:")
        for d, cnt in stats["recent_dates"]:
            print(f"    {d}: {cnt}只ETF")
        if stats["total_records"] == 0:
            print("\n  💡 提示: 运行 --record 采集今日数据入库")
        sys.exit(0)

    main(args.date, args.send, args.record)
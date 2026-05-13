---
name: etf-three-factor
description: 三因子ETF监控系统 — 追踪国家队（中央汇金）ETF操作信号。支持：① 数据获取（腾讯财经行情 + 东方财富份额）② 本地SQLite存档 ③ 三因子分析（量能P50% + 方向P20% + 份额P30%）④ HTML报告生成 ⑤ 邮件发送。当用户需要运行ETF三因子分析、查询国家队信号、查看每日监测报告、或设置定时任务时使用。
---

# etf-three-factor — 三因子ETF监控系统

## 核心文件

- **`scripts/etf_v6_threefactor.py`** — 主分析脚本，完整流水线
- **`scripts/etf_data_store.py`** — SQLite数据存储模块
- **`references/etf_model.md`** — 三因子模型详细说明
- **`references/config.md`** — 配置指南

---

## 调用模式

### 一键完整运行（推荐）
```bash
cd ~/.qclaw/skills/etf-three-factor/scripts
python3 etf_v6_threefactor.py
```
执行：获取数据 → 存档 → 三因子分析 → 生成HTML → 保存JSON

### 分功能调用

| 任务 | 命令 | 说明 |
|------|------|------|
| 仅采集当日份额入库 | `python3 etf_v6_threefactor.py --record` | 不跑分析，只采集push2实时份额 |
| 查看数据库状态 | `python3 etf_v6_threefactor.py --stats` | 显示记录数/日期范围/份额覆盖率 |
| 分析特定日期 | `python3 etf_v6_threefactor.py --date 2026-04-30` | 回溯历史分析 |
| 生成报告+发邮件 | `python3 etf_v6_threefactor.py --send` | 完整流水线+邮件发送至 28289062@qq.com |

---

## 输出文件

| 文件 | 位置 | 说明 |
|------|------|------|
| HTML报告 | `~/.qclaw/workspace/ETF三因子分析-终版.html` | 16:9可视化报告 |
| JSON数据 | `~/.qclaw/workspace/ETF三因子分析-终版.json` | 纯数据，方便程序调用 |
| SQLite DB | `~/.qclaw/workspace/etf_history.db` | 历史数据本地存储 |
| 份额历史 | `~/.qclaw/workspace/etf_shares_history.json` | 份额数据JSON备份 |

---

## 三因子模型（权重）

```
综合概率 = 量能概率 × 50% + 方向概率 × 20% + 份额概率 × 30%
```

| 因子 | 权重 | 数据来源 | 说明 |
|------|------|----------|------|
| 量能概率 | 50% | 腾讯财经API | 当日成交量 ÷ 20日均量（倍量） |
| 方向概率 | 20% | 腾讯财经API | 护盘特征：逆市涨+超额+前几日跌+尾盘 |
| 份额概率 | 30% | 东方财富push2 | 一级市场申赎，日份额变化/20日均 |

**信号分级：**
- 🔴 综合概率 ≥70% → 高确信，国家队大概率在增持
- 🟡 综合概率 50~70% → 中等关注
- 🟢 综合概率 <50% → 正常

---

## 监控ETF列表

| 代码 | 名称 | 跟踪指数 |
|------|------|----------|
| 510300 | 华泰柏瑞沪深300ETF | 沪深300 |
| 510310 | 易方达沪深300ETF | 沪深300 |
| 510330 | 华夏沪深300ETF | 沪深300 |
| 159919 | 嘉实沪深300ETF | 沪深300 |
| 510050 | 华夏上证50ETF | 上证50 |
| 510500 | 华泰柏瑞中证500ETF | 中证500 |
| 512100 | 南方中证1000ETF | 中证1000 |

---

## 邮件配置

使用环境变量 `QQMAIL_AUTH_CODE` 或 `SMTP_PASS` 存储QQ邮箱授权码：
```bash
export QQMAIL_AUTH_CODE="your_auth_code_here"
# 永久写入 ~/.zshrc 或 ~/.bashrc
```

邮件发送目标：`28289062@qq.com`（小贺FIRE了）

---

## 定时任务设置

建议每个工作日 16:30 运行（收盘后采集份额数据）：

```
openclaw cron add
  → name: "ETF三因子日报·交易日16:30"
  → schedule: "30 16 * * 1-5" (Asia/Shanghai)
  → message: "运行 ETF 三因子分析，然后发邮件"
  → sessionTarget: isolated
```

---

## 数据库查询示例

```python
import sys
sys.path.insert(0, "~/.qclaw/skills/etf-three-factor/scripts")
from etf_data_store import ETFDataStore

store = ETFDataStore()

# 查看数据库状态
stats = store.get_stats()
print(f"共{stats['total_records']}条记录，{stats['total_dates']}个交易日")

# 查询某日数据
rows = store.get_date_summary("2026-05-08")
for r in rows:
    print(f"{r['name']}: CP={r['composite_prob']}% 份额={r['shares_yi']}亿")

# 查询某ETF历史份额
shares = store.get_range(code="510300", start_date="2026-04-01")
```

更多模型细节和配置说明：
- 三因子模型详情 → `references/etf_model.md`
- 环境配置/邮件/SMTP → `references/config.md`

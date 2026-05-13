#!/usr/bin/env python3
"""
ETF本地数据存储模块 — SQLite数据库
=====================================
目的: 解决 push2 API 只提供最新份额数据、无法回溯历史的问题。

功能:
  - 自动建库建表
  - 每个交易日记录ETF行情+份额数据
  - 支持历史查询（日期范围、单只/全部ETF）
  - 与etf_v6_threefactor.py无缝集成

数据库位置: ~/.qclaw/workspace/etf_history.db
表: etf_daily — 每日每只ETF一条记录

使用示例:
  from etf_data_store import ETFDataStore
  store = ETFDataStore()
  store.record_today()                    # 记录当日数据
  store.get_shares("510300", "2026-04-30")  # 查询历史份额
  store.get_range("2026-04-01", "2026-04-30")  # 查询日期范围
"""

import sqlite3, json, os, sys
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/.qclaw/workspace/etf_history.db")

ETFS = {
    "510300": {"n": "华泰柏瑞沪深300ETF", "idx": "沪深300"},
    "510310": {"n": "易方达沪深300ETF",   "idx": "沪深300"},
    "510330": {"n": "华夏沪深300ETF",     "idx": "沪深300"},
    "159919": {"n": "嘉实沪深300ETF",     "idx": "沪深300"},
    "510050": {"n": "华夏上证50ETF",      "idx": "上证50"},
    "510500": {"n": "华泰柏瑞中证500ETF",  "idx": "中证500"},
    "512100": {"n": "南方中证1000ETF",    "idx": "中证1000"},
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS etf_daily (
    date        TEXT    NOT NULL,  -- YYYY-MM-DD
    code        TEXT    NOT NULL,  -- ETF代码
    name        TEXT,              -- ETF名称
    idx_name    TEXT,              -- 跟踪指数
    close_price REAL,              -- 收盘价
    change_pct  REAL,              -- 涨跌幅(%)
    volume      REAL,              -- 成交量(万手)
    volume_ma20 REAL,              -- 20日均量(万手)
    volume_ratio REAL,             -- 倍量(v/ma20)
    shares_yi   REAL,              -- 份额(亿份)
    shares_delta_yi  REAL,         -- 份额日变(亿份)
    shares_delta_pct REAL,         -- 份额日变(%)
    vol_prob    REAL,              -- 量能概率(%)
    dir_prob    REAL,              -- 方向概率(%)
    share_prob  REAL,              -- 份额概率(%)
    composite_prob REAL,           -- 综合概率(%)
    idx_chg     REAL,              -- 当日沪深300涨跌幅(%)
    signal_level TEXT,             -- 信号级别: HIGH/MID/LOW
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (date, code)
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_etf_code ON etf_daily(code);",
    "CREATE INDEX IF NOT EXISTS idx_etf_date ON etf_daily(date);",
    "CREATE INDEX IF NOT EXISTS idx_etf_date_code ON etf_daily(date, code);",
]

class ETFDataStore:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _init_db(self):
        """建库建表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(CREATE_TABLE_SQL)
            for idx_sql in CREATE_INDEX_SQL:
                conn.execute(idx_sql)
            conn.commit()

    # ================================================================
    # 写入
    # ================================================================

    def upsert_record(self, date, code, data):
        """
        插入或更新一条ETF日数据
        data: dict with keys matching columns
        """
        columns = [
            "date", "code", "name", "idx_name", "close_price", "change_pct",
            "volume", "volume_ma20", "volume_ratio",
            "shares_yi", "shares_delta_yi", "shares_delta_pct",
            "vol_prob", "dir_prob", "share_prob", "composite_prob",
            "idx_chg", "signal_level",
        ]
        placeholders = ", ".join(["?" for _ in columns])
        upsert_cols = ", ".join([f"{c}=excluded.{c}" for c in columns if c not in ("date", "code")])

        sql = f"""
        INSERT INTO etf_daily ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(date, code) DO UPDATE SET
            {upsert_cols},
            updated_at = datetime('now','localtime');
        """
        values = tuple(data.get(c) for c in columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(sql, values)
            conn.commit()
        return True

    def batch_upsert(self, date, records):
        """批量写入同一天多只ETF"""
        count = 0
        for code, data in records.items():
            if self.upsert_record(date, code, data):
                count += 1
        return count

    # ================================================================
    # 查询
    # ================================================================

    def get_shares(self, code, date):
        """
        查询某只ETF在指定日期的份额数据
        返回: dict 或 None
        """
        sql = "SELECT shares_yi, shares_delta_yi, shares_delta_pct, share_prob FROM etf_daily WHERE code=? AND date=?"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, (code, date)).fetchone()
            return dict(row) if row else None

    def get_latest_shares(self, code, before_date=None):
        """
        获取某只ETF在指定日期之前（含）的最新份额记录
        用于回溯分析时获取最近可用份额数据
        """
        if before_date is None:
            before_date = datetime.now().strftime("%Y-%m-%d")
        sql = """
            SELECT date, shares_yi, shares_delta_yi, shares_delta_pct, share_prob
            FROM etf_daily
            WHERE code=? AND date <= ? AND shares_yi IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, (code, before_date)).fetchone()
            return dict(row) if row else None

    def get_range(self, code=None, start_date=None, end_date=None):
        """
        查询日期范围内的数据
        code: None=全部ETF, 指定=单只
        start_date/end_date: YYYY-MM-DD
        """
        sql = "SELECT * FROM etf_daily WHERE 1=1"
        params = []
        if code:
            sql += " AND code=?"
            params.append(code)
        if start_date:
            sql += " AND date>=?"
            params.append(start_date)
        if end_date:
            sql += " AND date<=?"
            params.append(end_date)
        sql += " ORDER BY date DESC, code ASC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_date_summary(self, date):
        """获取某日的汇总数据（全部ETF）"""
        return self.get_range(start_date=date, end_date=date)

    def get_stats(self):
        """获取数据库统计信息"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            stats = {}
            row = conn.execute("SELECT COUNT(*) as cnt FROM etf_daily").fetchone()
            stats["total_records"] = row["cnt"]
            row = conn.execute("SELECT COUNT(DISTINCT date) as cnt FROM etf_daily").fetchone()
            stats["total_dates"] = row["cnt"]
            row = conn.execute("SELECT MIN(date) as mn, MAX(date) as mx FROM etf_daily").fetchone()
            stats["date_range"] = (row["mn"], row["mx"])
            row = conn.execute(
                "SELECT date, COUNT(*) as cnt FROM etf_daily GROUP BY date ORDER BY date DESC LIMIT 5"
            ).fetchall()
            stats["recent_dates"] = [(r["date"], r["cnt"]) for r in row]

            # 份额覆盖情况
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM etf_daily WHERE shares_yi IS NOT NULL"
            ).fetchone()
            stats["records_with_shares"] = row["cnt"]

            return stats

    # ================================================================
    # 与三因子模型集成
    # ================================================================

    def get_share_for_backtest(self, code, target_date):
        """
        回溯分析用：获取指定日期的份额数据
        优先查本地DB，本地没有则返回None（提示不可回溯）
        """
        result = self.get_shares(code, target_date)
        if result:
            return {
                "shares_yi": result["shares_yi"],
                "delta_yi": result["shares_delta_yi"],
                "delta_pct": result["shares_delta_pct"],
                "source": "local_db",
            }
        # 尝试获取最近的历史
        latest = self.get_latest_shares(code, target_date)
        if latest:
            return {
                "shares_yi": latest["shares_yi"],
                "delta_yi": None,
                "delta_pct": None,
                "source": "local_db_latest",
                "latest_date": latest["date"],
                "note": f"目标日{target_date}无份额记录，使用最近可用日{latest['date']}",
            }
        return None

    def record_from_v6_result(self, date, etf_results, idx_chg):
        """
        从三因子分析结果中批量记录数据
        etf_results: {code: {name, idx_name, chg, v, vma, vr, vp, dp, sp, cp, shares_yi, delta_yi, delta_pct}}
        """
        records = {}
        for code, r in etf_results.items():
            level = "HIGH" if r.get("cp", 0) >= 70 else ("MID" if r.get("cp", 0) >= 50 else "LOW")
            records[code] = {
                "date": date,
                "code": code,
                "name": r.get("name", ETFS.get(code, {}).get("n", "")),
                "idx_name": r.get("idx_name", ETFS.get(code, {}).get("idx", "")),
                "close_price": r.get("c"),
                "change_pct": r.get("chg"),
                "volume": r.get("v"),
                "volume_ma20": r.get("vma"),
                "volume_ratio": r.get("vr"),
                "shares_yi": r.get("shares_yi"),
                "shares_delta_yi": r.get("delta_yi"),
                "shares_delta_pct": r.get("delta_pct"),
                "vol_prob": r.get("vp"),
                "dir_prob": r.get("dp"),
                "share_prob": r.get("sp"),
                "composite_prob": r.get("cp"),
                "idx_chg": idx_chg,
                "signal_level": level,
            }
        return self.batch_upsert(date, records)


# ================================================================
# 命令行工具
# ================================================================

if __name__ == "__main__":
    store = ETFDataStore()
    stats = store.get_stats()
    print("=" * 60)
    print("📊 ETF历史数据库状态")
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
        print("\n  ⚠️ 数据库为空，请先运行数据采集生成记录。")
    else:
        print(f"\n  示例查询（最新日期的数据）:")
        latest_date = stats["recent_dates"][0][0]
        rows = store.get_date_summary(latest_date)
        for r in rows:
            sig = "🔴" if r["composite_prob"] and r["composite_prob"] >= 70 else ("🟡" if r["composite_prob"] and r["composite_prob"] >= 50 else "⚪")
            shares = f"份额{r['shares_yi']:.1f}亿" if r["shares_yi"] else "份额N/A"
            print(f"    {sig} {r['name'][:10]:12s} | 量{r['volume_ratio']:.2f}x | CP{r['composite_prob']:.0f}% | {shares}")
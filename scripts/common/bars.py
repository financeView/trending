"""bars.db：双口径 qfq + raw（market-data-contract §4）。"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from typing import Optional

from scripts.common.http import RateLimiter, call_with_retry
from scripts.common.ts_code import to_sina_symbol, to_ts_code

DEFAULT_BARS_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache", "bars.db"
)

BARS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
  ts_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open_qfq REAL, high_qfq REAL, low_qfq REAL, close_qfq REAL,
  open_raw REAL, high_raw REAL, low_raw REAL, close_raw REAL,
  preclose_raw REAL,
  volume REAL, amount REAL, turnover REAL,
  float_mv REAL,
  limit_up REAL, limit_down REAL,
  is_suspended INTEGER NOT NULL DEFAULT 0,
  is_st INTEGER NOT NULL DEFAULT 0,
  bar_source TEXT,
  flag_source TEXT,
  limit_source TEXT,
  fetched_at TEXT,
  PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS sync_meta (
  ts_code TEXT PRIMARY KEY,
  last_bar_date TEXT,
  qfq_rebuild_token TEXT,
  preferred_source TEXT
);
"""


def bars_conn(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or DEFAULT_BARS_DB
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(BARS_SCHEMA)
    conn.commit()
    return conn


def _fetch_sina_daily(symbol: str, adjust: str):
    import akshare as ak

    # akshare stock_zh_a_daily: symbol like sh600000; adjust "" | qfq | hfq
    return ak.stock_zh_a_daily(symbol=symbol, adjust=adjust)


def sync_symbol_bars(
    conn: sqlite3.Connection,
    ts_code: str,
    end: date,
    *,
    start: Optional[date] = None,
    source: Optional[str] = None,
    limiter: Optional[RateLimiter] = None,
) -> int:
    """拉取并 UPSERT 一只股票的 raw+qfq。返回写入行数。"""
    source = source or os.environ.get("BARS_SOURCE", "sina")
    if source != "sina":
        raise NotImplementedError("P0 only implements BARS_SOURCE=sina")

    ts = to_ts_code(ts_code)
    symbol = to_sina_symbol(ts)
    limiter = limiter or RateLimiter(3.0)
    start = start or (end - timedelta(days=400))

    raw_df = call_with_retry(
        lambda: _fetch_sina_daily(symbol, ""),
        limiter,
        desc="sina_raw_%s" % symbol,
    )
    qfq_df = call_with_retry(
        lambda: _fetch_sina_daily(symbol, "qfq"),
        limiter,
        desc="sina_qfq_%s" % symbol,
    )

    import pandas as pd

    def _norm(df, prefix):
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        rename = {
            "open": "%s_open" % prefix,
            "high": "%s_high" % prefix,
            "low": "%s_low" % prefix,
            "close": "%s_close" % prefix,
        }
        d = d.rename(columns=rename)
        cols = ["date"] + list(rename.values())
        if "volume" in d.columns:
            cols.append("volume")
        if "amount" in d.columns:
            cols.append("amount")
        return d[cols]

    raw_n = _norm(raw_df, "raw")
    qfq_n = _norm(qfq_df, "qfq")
    merged = pd.merge(raw_n, qfq_n, on="date", how="outer", suffixes=("", "_q"))
    # volume/amount from raw side
    if "volume_q" in merged.columns:
        merged["volume"] = merged["volume"].fillna(merged["volume_q"])
        merged.drop(columns=["volume_q"], inplace=True, errors="ignore")
    if "amount_q" in merged.columns:
        merged["amount"] = merged["amount"].fillna(merged["amount_q"])
        merged.drop(columns=["amount_q"], inplace=True, errors="ignore")

    start_s, end_s = start.isoformat(), end.isoformat()
    merged = merged[(merged["date"] >= start_s) & (merged["date"] <= end_s)]

    from datetime import datetime

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    rows = 0
    for _, r in merged.iterrows():
        conn.execute(
            """
            INSERT OR REPLACE INTO bars (
              ts_code, trade_date,
              open_qfq, high_qfq, low_qfq, close_qfq,
              open_raw, high_raw, low_raw, close_raw,
              volume, amount,
              is_suspended, is_st, bar_source, fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?)
            """,
            (
                ts,
                r["date"],
                r.get("qfq_open"),
                r.get("qfq_high"),
                r.get("qfq_low"),
                r.get("qfq_close"),
                r.get("raw_open"),
                r.get("raw_high"),
                r.get("raw_low"),
                r.get("raw_close"),
                r.get("volume"),
                r.get("amount"),
                source,
                now,
            ),
        )
        rows += 1
    conn.execute(
        """
        INSERT OR REPLACE INTO sync_meta (ts_code, last_bar_date, preferred_source)
        VALUES (?, ?, ?)
        """,
        (ts, end_s, source),
    )
    conn.commit()
    return rows

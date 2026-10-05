"""bars.db：双口径 qfq + raw + flags/limits（market-data-contract §3–§4）。"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from scripts.common.http import RateLimiter, call_with_retry
from scripts.common.ts_code import to_baostock_code, to_sina_symbol, to_ts_code

DEFAULT_BARS_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache", "bars.db"
)

FLAG_SOURCE_BAOSTOCK = "baostock"
LIMIT_SOURCE_EM = "em_f51f52"

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

_OHLC_UPSERT = """
INSERT INTO bars (
  ts_code, trade_date,
  open_qfq, high_qfq, low_qfq, close_qfq,
  open_raw, high_raw, low_raw, close_raw,
  volume, amount,
  bar_source, fetched_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(ts_code, trade_date) DO UPDATE SET
  open_qfq=excluded.open_qfq,
  high_qfq=excluded.high_qfq,
  low_qfq=excluded.low_qfq,
  close_qfq=excluded.close_qfq,
  open_raw=excluded.open_raw,
  high_raw=excluded.high_raw,
  low_raw=excluded.low_raw,
  close_raw=excluded.close_raw,
  volume=excluded.volume,
  amount=excluded.amount,
  bar_source=excluded.bar_source,
  fetched_at=excluded.fetched_at
"""


def bars_conn(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or DEFAULT_BARS_DB
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(BARS_SCHEMA)
    conn.commit()
    return conn


def load_ohlc_limits(bars_path: str, trade_date: str, codes: Sequence[str]) -> Dict[str, dict]:
    """open_raw / close_raw / limits / is_suspended for fill_day. Empty if db missing."""
    if not os.path.exists(bars_path) or not codes:
        return {}
    conn = bars_conn(bars_path)
    out: Dict[str, dict] = {}
    try:
        for ts in codes:
            row = conn.execute(
                """
                SELECT open_raw, close_raw, limit_up, limit_down, is_suspended
                FROM bars WHERE ts_code=? AND trade_date=?
                """,
                (ts, trade_date),
            ).fetchone()
            if row:
                out[ts] = {
                    "open_raw": row[0],
                    "close_raw": row[1],
                    "limit_up": row[2],
                    "limit_down": row[3],
                    "is_suspended": row[4],
                }
    finally:
        conn.close()
    return out


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _assert_source_not_mixed(conn: sqlite3.Connection, ts_code: str, source: str) -> None:
    """禁止同一票混用 sina/em（market-data-contract §7.1）。"""
    row = conn.execute(
        "SELECT preferred_source FROM sync_meta WHERE ts_code=?", (ts_code,)
    ).fetchone()
    if row and row[0] and row[0] != source:
        raise ValueError(
            "BARS_SOURCE mix forbidden for %s: preferred=%s requested=%s"
            % (ts_code, row[0], source)
        )


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
    """拉取并 UPSERT 一只股票的 raw+qfq。不覆盖 flags / limit_* / float_mv。"""
    source = source or os.environ.get("BARS_SOURCE", "sina")
    if source != "sina":
        raise NotImplementedError("MVP only implements BARS_SOURCE=sina")

    ts = to_ts_code(ts_code)
    _assert_source_not_mixed(conn, ts, source)
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
    if "volume_q" in merged.columns:
        merged["volume"] = merged["volume"].fillna(merged["volume_q"])
        merged.drop(columns=["volume_q"], inplace=True, errors="ignore")
    if "amount_q" in merged.columns:
        merged["amount"] = merged["amount"].fillna(merged["amount_q"])
        merged.drop(columns=["amount_q"], inplace=True, errors="ignore")

    start_s, end_s = start.isoformat(), end.isoformat()
    merged = merged[(merged["date"] >= start_s) & (merged["date"] <= end_s)]

    now = _utc_now()
    rows = 0
    for _, r in merged.iterrows():
        conn.execute(
            _OHLC_UPSERT,
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
        INSERT INTO sync_meta (ts_code, last_bar_date, preferred_source)
        VALUES (?, ?, ?)
        ON CONFLICT(ts_code) DO UPDATE SET
          last_bar_date=excluded.last_bar_date,
          preferred_source=excluded.preferred_source
        """,
        (ts, end_s, source),
    )
    conn.commit()
    return rows


def apply_flag_rows(
    conn: sqlite3.Connection,
    rows: Sequence[Tuple[str, str, int, int]],
    *,
    flag_source: str = FLAG_SOURCE_BAOSTOCK,
    commit: bool = True,
) -> int:
    """写入 is_st / is_suspended。rows: (ts_code, trade_date, is_suspended, is_st)。

    仅更新 flags；若无 bar 行则插入仅含 flags 的占位行（OHLC 仍空）。
    """
    now = _utc_now()
    n = 0
    for ts_code, trade_date, is_suspended, is_st in rows:
        ts = to_ts_code(ts_code)
        sus = 1 if int(is_suspended) else 0
        st = 1 if int(is_st) else 0
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date, is_suspended, is_st, flag_source, fetched_at
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT(ts_code, trade_date) DO UPDATE SET
              is_suspended=excluded.is_suspended,
              is_st=excluded.is_st,
              flag_source=excluded.flag_source,
              fetched_at=excluded.fetched_at
            """,
            (ts, trade_date, sus, st, flag_source, now),
        )
        n += 1
    if commit:
        conn.commit()
    return n


def fetch_baostock_flags(
    ts_code: str,
    start: date,
    end: date,
    *,
    limiter: Optional[RateLimiter] = None,
) -> List[Tuple[str, str, int, int]]:
    """网络：BaoStock 日线 tradestatus / isST → (ts_code, date, is_suspended, is_st)。"""
    import baostock as bs

    ts = to_ts_code(ts_code)
    code = to_baostock_code(ts)
    limiter = limiter or RateLimiter(2.0)

    def _query():
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError("baostock login: %s" % lg.error_msg)
        try:
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,tradestatus,isST",
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            if rs.error_code != "0":
                raise RuntimeError("baostock query %s: %s" % (code, rs.error_msg))
            out: List[Tuple[str, str, int, int]] = []
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                # tradestatus: 1=正常, 0=停牌；isST: 1=ST
                trade_status = str(row[2]).strip()
                is_st_raw = str(row[3]).strip()
                is_suspended = 0 if trade_status == "1" else 1
                is_st = 1 if is_st_raw in ("1", "True", "true") else 0
                out.append((ts, row[0], is_suspended, is_st))
            return out
        finally:
            bs.logout()

    return call_with_retry(
        _query, limiter, desc="baostock_flags_%s" % code, attempts=2, backoffs=(2, 5)
    )


def sync_baostock_flags(
    conn: sqlite3.Connection,
    ts_code: str,
    end: date,
    *,
    start: Optional[date] = None,
    limiter: Optional[RateLimiter] = None,
) -> int:
    """拉取 BaoStock flags 并 UPSERT 进 bars。"""
    start = start or (end - timedelta(days=400))
    rows = fetch_baostock_flags(ts_code, start, end, limiter=limiter)
    return apply_flag_rows(conn, rows)


def apply_limit_rows(
    conn: sqlite3.Connection,
    trade_date: str,
    limits: Dict[str, Tuple[float, float]],
    *,
    limit_source: str = LIMIT_SOURCE_EM,
    commit: bool = True,
) -> int:
    """写入当日 limit_up / limit_down（raw 空间）。limits: ts_code → (up, down)。"""
    now = _utc_now()
    n = 0
    for ts_code, (up, down) in limits.items():
        if up is None or down is None:
            continue
        try:
            up_f = float(up)
            down_f = float(down)
        except (TypeError, ValueError):
            continue
        if up_f <= 0 or down_f <= 0:
            continue
        ts = to_ts_code(ts_code)
        conn.execute(
            """
            INSERT INTO bars (
              ts_code, trade_date, limit_up, limit_down, limit_source, fetched_at
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT(ts_code, trade_date) DO UPDATE SET
              limit_up=excluded.limit_up,
              limit_down=excluded.limit_down,
              limit_source=excluded.limit_source,
              fetched_at=excluded.fetched_at
            """,
            (ts, trade_date, up_f, down_f, limit_source, now),
        )
        n += 1
    if commit:
        conn.commit()
    return n


def fetch_em_limits_batch(
    ts_codes: Optional[Iterable[str]] = None,
    *,
    limiter: Optional[RateLimiter] = None,
) -> Dict[str, Tuple[float, float]]:
    """网络：东财 clist f51/f52 → {ts_code: (limit_up, limit_down)}。

    若传入 ts_codes 则只保留交集；否则返回全 A 快照中有限价的票。
    """
    from scripts.common.em_client import fetch_limit_up_down_all_a

    limiter = limiter or RateLimiter(2.0)
    raw = call_with_retry(
        fetch_limit_up_down_all_a, limiter, desc="em_f51f52", attempts=2, backoffs=(3, 10)
    )
    wanted = {to_ts_code(c) for c in ts_codes} if ts_codes is not None else None
    out: Dict[str, Tuple[float, float]] = {}
    for ts, up, down in raw:
        if wanted is not None and ts not in wanted:
            continue
        out[ts] = (up, down)
    return out


def sync_em_limits_asof(
    conn: sqlite3.Connection,
    trade_date: date,
    *,
    ts_codes: Optional[Iterable[str]] = None,
    limiter: Optional[RateLimiter] = None,
) -> int:
    """将东财当日涨跌停写入 trade_date（session asof）。历史日勿用今日 spot 回刷。"""
    limits = fetch_em_limits_batch(ts_codes, limiter=limiter)
    return apply_limit_rows(conn, trade_date.isoformat(), limits)

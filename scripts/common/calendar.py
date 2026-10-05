"""交易日历（akshare 新浪）+ 交易日滞后 API。"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import List, Optional

_cache: Optional[List[dt.date]] = None
CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache", "trade_dates.json"
)


def _repo_cache_file() -> str:
    return os.path.abspath(CACHE_FILE)


def trade_dates(force_refresh: bool = False) -> List[dt.date]:
    """升序交易日列表。接口失败时用文件缓存降级。"""
    global _cache
    if _cache is not None and not force_refresh:
        return _cache
    try:
        import akshare as ak
        import pandas as pd

        df = ak.tool_trade_date_hist_sina()
        _cache = sorted(pd.to_datetime(df["trade_date"]).dt.date.tolist())
        try:
            os.makedirs(os.path.dirname(_repo_cache_file()), exist_ok=True)
            with open(_repo_cache_file(), "w", encoding="utf-8") as f:
                json.dump([str(d) for d in _cache], f)
        except Exception:
            pass
        return _cache
    except Exception as e:
        path = _repo_cache_file()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _cache = sorted(
                    dt.datetime.strptime(x, "%Y-%m-%d").date() for x in json.load(f)
                )
            print(
                "[warn] 交易日历接口失败(%s)，使用文件缓存(%d天,最新%s)"
                % (str(e)[:50], len(_cache), _cache[-1]),
                file=sys.stderr,
            )
            return _cache
        raise


def load_trade_dates_from_list(dates: List[str]) -> List[dt.date]:
    """测试用：注入日历并写入进程缓存。"""
    global _cache
    _cache = sorted(dt.datetime.strptime(x, "%Y-%m-%d").date() for x in dates)
    return _cache


def clear_trade_date_cache() -> None:
    global _cache
    _cache = None


def is_trade_day(d: dt.date) -> bool:
    return d in set(trade_dates())


def latest_trade_day(today: Optional[dt.date] = None) -> dt.date:
    if today is None:
        now = dt.datetime.utcnow()
        if now.hour >= 15:
            print(
                "[warn] UTC %s 启动（北京时间已过零点），trade_date 锚定为 %s"
                % (now.strftime("%H:%M"), (now.date() - dt.timedelta(days=1))),
                file=sys.stderr,
            )
        today = now.date()
    days = [d for d in trade_dates() if d <= today]
    if not days:
        raise RuntimeError("交易日历异常：无可用交易日")
    return days[-1]


def shift_trade_day(d: dt.date, n: int) -> Optional[dt.date]:
    days = trade_dates()
    i = days.index(d)
    j = i + n
    if j < 0 or j >= len(days):
        return None
    return days[j]


def prev_trade_date(d: dt.date) -> Optional[dt.date]:
    return shift_trade_day(d, -1)


def next_trade_date(d: dt.date) -> Optional[dt.date]:
    return shift_trade_day(d, 1)


def trading_days_inclusive(start: dt.date, end: dt.date) -> List[dt.date]:
    return [d for d in trade_dates() if start <= d <= end]

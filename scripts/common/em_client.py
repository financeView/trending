"""东财直连：当日涨跌停 f51/f52（market-data-contract §3）。

继承 economy-strategy：push2delay 优先 + host 轮换 + 浏览器 UA。
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import pandas as pd
import requests

from scripts.common.ts_code import to_ts_code

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

HOSTS = (
    "push2delay.eastmoney.com",
    "push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "16.push2.eastmoney.com",
    "33.push2.eastmoney.com",
)

CLIST_PATH = "/api/qt/clist/get"
# 全A（沪深主板/创业/科创）；不含北交所
FS_ALL_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def _get_json(host: str, path: str, params: dict, timeout: int = 15, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(
                "https://%s%s" % (host, path),
                params=params,
                headers={"User-Agent": UA},
                timeout=timeout,
            )
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(2**i, 8))
    raise RuntimeError("host %s: %s" % (host, last))


def fetch_clist_all_a(fields: List[str], rate_wait: float = 0.3) -> pd.DataFrame:
    """全 A clist。fields 如 f12/f51/f52。"""
    base = {
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f12",
        "fs": FS_ALL_A,
        "fields": ",".join(fields),
    }
    last_err = None
    for host in HOSTS:
        try:
            first = _get_json(host, CLIST_PATH, dict(base, pn=1, pz=100))
            data = first.get("data") or {}
            total = data.get("total") or 0
            rows = list(data.get("diff") or [])
            if not rows:
                raise RuntimeError("空响应")
            for pn in range(2, int(total / 100) + 2):
                more = _get_json(host, CLIST_PATH, dict(base, pn=pn, pz=100))
                rows += (more.get("data") or {}).get("diff") or []
                time.sleep(rate_wait)
            if total and len(rows) < total * 0.98:
                raise RuntimeError("缺页 %d/%d" % (len(rows), total))
            return pd.DataFrame(rows)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError("clist 全部 host 失败: %s" % last_err)


def _infer_ts_code(code6: str, row: dict) -> Optional[str]:
    code6 = str(code6).zfill(6)
    # f13: 0=SZ, 1=SH（clist 常见）
    mkt = row.get("f13")
    if mkt is not None:
        try:
            m = int(mkt)
            return "%s.%s" % (code6, "SH" if m == 1 else "SZ")
        except (TypeError, ValueError):
            pass
    try:
        return to_ts_code(code6)
    except ValueError:
        return None


def fetch_limit_up_down_all_a() -> List[Tuple[str, float, float]]:
    """返回 [(ts_code, limit_up, limit_down), ...]；价格为 raw（东财未复权限价）。"""
    # f12 代码 f13 市场 f51 涨停 f52 跌停
    df = fetch_clist_all_a(["f12", "f13", "f51", "f52"])
    out: List[Tuple[str, float, float]] = []
    for _, r in df.iterrows():
        ts = _infer_ts_code(r.get("f12"), r.to_dict())
        if not ts:
            continue
        try:
            up = float(r["f51"])
            down = float(r["f52"])
        except (TypeError, ValueError, KeyError):
            continue
        if up <= 0 or down <= 0:
            continue
        out.append((ts, up, down))
    return out

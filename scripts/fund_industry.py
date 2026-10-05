"""Aggregate public-fund stock holdings by the repository's SW2021 taxonomy.

The source returns market-wide holdings aggregated by stock, so individual fund
holdings are never persisted. Values are kept in the source-native unit (10k CNY)
for arithmetic and rendered in 100m CNY (亿元).
"""
from __future__ import annotations

import html
import io
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from importlib.metadata import PackageNotFoundError, version
from numbers import Integral
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml

from scripts.common.sws_tls import verified_sws_ca_bundle

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY = ROOT / "config" / "taxonomy" / "sw2021_repository_tree.yaml"
MIN_REPORT_DATE = date(2021, 9, 30)  # first full quarter after SW2021 took effect
CNINFO_FIELDS = ("股票代码", "报告期", "持股总市值")
A_SHARE_PREFIXES = (
    "000", "001", "002", "003", "300", "301",
    "600", "601", "603", "605", "688", "689",
)
WAN_TO_YI = Decimal("10000")  # 10,000 x 万元 = 1 亿元
HISTORY_DENOMINATOR = (
    "all SW2021-mapped Shanghai/Shenzhen A-share stock positions in this CNINFO "
    "report period across funds"
)


class _RateLimiter:
    """Module-local limiter; fund jobs do not depend on trend utilities."""

    def __init__(self, per_second: float = 2.0) -> None:
        self.min_interval = 1.0 / per_second
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def _call_with_retry(
    fn: Callable[[], Any],
    *,
    limiter: _RateLimiter,
    attempts: int = 3,
    backoffs: Sequence[float] = (2, 5),
    desc: str,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        limiter.wait()
        try:
            return fn()
        except Exception as exc:  # network/source errors fail closed
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
    raise RuntimeError(f"call failed after {attempts} attempts: {desc}: {last_error}")


class FundIndustryError(RuntimeError):
    """Base error for source, taxonomy, or report-period failures."""


class ReportUnavailableError(FundIndustryError):
    """Raised when no public holdings table exists for a requested period."""


@dataclass(frozen=True)
class Taxonomy:
    map_version: str
    l1_by_id: Mapping[str, Mapping[str, Any]]
    l2_by_code: Mapping[str, Mapping[str, Any]]


def load_taxonomy(path: str | Path | None = None) -> Taxonomy:
    """Load and validate the full 14-L1 / 134-L2 repository taxonomy."""
    config_path = Path(path) if path is not None else DEFAULT_TAXONOMY
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict) or not raw.get("map_version"):
        raise ValueError("taxonomy must be a mapping with map_version")
    l1_nodes = raw.get("l1")
    if not isinstance(l1_nodes, list) or not l1_nodes:
        raise ValueError("taxonomy must contain a non-empty l1 list")

    l1_by_id: dict[str, dict[str, Any]] = {}
    l2_by_code: dict[str, dict[str, Any]] = {}
    for l1 in l1_nodes:
        if not isinstance(l1, dict):
            raise ValueError("each l1 node must be a mapping")
        l1_id = str(l1.get("id", "")).strip()
        l1_name = str(l1.get("name", "")).strip()
        if not l1_id or not l1_name or l1_id in l1_by_id:
            raise ValueError(f"invalid or duplicate L1 node: {l1!r}")
        children = l1.get("level2")
        if not isinstance(children, list) or not children:
            raise ValueError(f"L1 {l1_id} must have L2 children")
        normalized_l1 = dict(l1)
        normalized_l1["id"] = l1_id
        normalized_l1["name"] = l1_name
        l1_by_id[l1_id] = normalized_l1
        for l2 in children:
            if not isinstance(l2, dict):
                raise ValueError(f"L2 node under {l1_id} must be a mapping")
            code = str(l2.get("code", "")).strip()
            name = str(l2.get("name", "")).strip()
            if not re.fullmatch(r"\d{6}", code) or not name or code in l2_by_code:
                raise ValueError(f"invalid or duplicate L2 node: {l2!r}")
            l2_by_code[code] = {
                "code": code,
                "name": name,
                "l1_id": l1_id,
                "l1_name": l1_name,
            }
    if len(l1_by_id) != 14 or len(l2_by_code) != 134:
        raise ValueError(
            f"expected repository taxonomy 14/134; got {len(l1_by_id)}/{len(l2_by_code)}"
        )
    return Taxonomy(str(raw["map_version"]), l1_by_id, l2_by_code)


def resolve_l1(value: str, taxonomy: Taxonomy) -> Mapping[str, Any]:
    """Resolve an L1 id/name or the workflow's ``id | name`` choice value."""
    token = str(value or "").strip().split("|", 1)[0].strip()
    if token in taxonomy.l1_by_id:
        return taxonomy.l1_by_id[token]
    matches = [node for node in taxonomy.l1_by_id.values() if node["name"] == token]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"unknown L1 industry {value!r}; use an exact L1 id or name")


def resolve_l2(value: str, l1_id: str, taxonomy: Taxonomy) -> Mapping[str, Any]:
    """Resolve an L2 SW code/name and enforce its parent-child relationship."""
    token = str(value or "").strip()
    if token in taxonomy.l2_by_code:
        node = taxonomy.l2_by_code[token]
    else:
        matches = [
            item for item in taxonomy.l2_by_code.values()
            if item["l1_id"] == l1_id and item["name"] == token
        ]
        if len(matches) != 1:
            raise ValueError(
                f"unknown L2 industry {value!r} under {l1_id}; use an exact SW2021 L2 code or name"
            )
        node = matches[0]
    if node["l1_id"] != l1_id:
        parent = taxonomy.l1_by_id[l1_id]["name"]
        raise ValueError(
            f"L2 {node['code']} {node['name']} belongs to {node['l1_id']} ({node['l1_name']}), "
            f"not selected L1 {l1_id} ({parent})"
        )
    return node


def parse_report_date(value: str | date) -> date:
    """Parse a YYYYMMDD/ISO date and require a supported quarter end."""
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        token = str(value).strip()
        try:
            parsed = datetime.strptime(token, "%Y%m%d").date() if re.fullmatch(r"\d{8}", token) else date.fromisoformat(token[:10])
        except ValueError as exc:
            raise ValueError("report date must be YYYYMMDD or YYYY-MM-DD") from exc
    quarter_ends = {(3, 31), (6, 30), (9, 30), (12, 31)}
    if (parsed.month, parsed.day) not in quarter_ends:
        raise ValueError(f"{parsed.isoformat()} is not a calendar-quarter reporting date")
    if parsed < MIN_REPORT_DATE:
        raise ValueError(
            f"{parsed.isoformat()} predates this repository's SW2021 taxonomy coverage; "
            f"earliest supported quarter is {MIN_REPORT_DATE.isoformat()}"
        )
    return parsed


def _quarter_ends(on_or_before: date) -> list[date]:
    ends = [date(year, month, day) for year in range(MIN_REPORT_DATE.year, on_or_before.year + 1)
            for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return sorted((item for item in ends if MIN_REPORT_DATE <= item <= on_or_before), reverse=True)


def rows_from_frame(value: Any) -> list[dict[str, Any]]:
    """Convert a pandas-like frame or iterable of mappings into plain records."""
    if value is None:
        return []
    if getattr(value, "empty", False):
        return []
    if hasattr(value, "to_dict"):
        try:
            return list(value.to_dict(orient="records"))
        except TypeError:
            pass
    return [dict(row) for row in value]


def _is_akshare_empty_period_error(exc: BaseException) -> bool:
    """AKShare 1.18.64 raises this KeyError when CNINFO returns zero records."""
    message = str(exc)
    return isinstance(exc, KeyError) and "None of [Index" in message and "[columns]" in message


def fetch_cninfo_report(report_date: date) -> list[dict[str, Any]]:
    """Fetch the public CNINFO all-funds-by-stock table for one report date.

    AkShare wraps CNINFO's public web endpoint and requires no user API key. The
    library currently raises a KeyError rather than returning an empty frame when
    CNINFO has no records for a period; that exact empty-result shape means
    "not published yet". Other errors fail closed and are retried.
    """
    import akshare as ak

    date_token = report_date.strftime("%Y%m%d")

    def call() -> Any:
        try:
            return ak.fund_report_stock_cninfo(date=date_token)
        except KeyError as exc:
            if _is_akshare_empty_period_error(exc):
                return []
            raise

    frame = _call_with_retry(
        call,
        limiter=_RateLimiter(per_second=2.0),
        attempts=3,
        backoffs=(2, 5),
        desc=f"CNINFO fund report holdings {date_token}",
    )
    records = rows_from_frame(frame)
    if not records:
        return []
    columns = set(records[0])
    missing = set(CNINFO_FIELDS) - columns
    if missing:
        raise FundIndustryError(f"CNINFO holdings schema missing required fields: {sorted(missing)}")
    return records


def _parse_row_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    token = str(value).strip()
    if not token or token.lower() in {"nan", "nat", "none"}:
        return None
    try:
        return date.fromisoformat(token[:10])
    except ValueError:
        return None


def _validated_records(records: Iterable[Mapping[str, Any]], report_date: date) -> list[dict[str, Any]]:
    rows = [dict(item) for item in records]
    if not rows:
        return []
    actual_dates = {_parse_row_date(row.get("报告期")) for row in rows}
    if actual_dates != {report_date}:
        raise FundIndustryError(
            f"CNINFO returned unexpected report dates {sorted(str(x) for x in actual_dates)} "
            f"for request {report_date.isoformat()}"
        )
    return rows


def fetch_latest_report(
    *,
    report_date: str | date | None = None,
    as_of: date | None = None,
    fetcher: Callable[[date], Iterable[Mapping[str, Any]]] | None = None,
) -> tuple[date, list[dict[str, Any]]]:
    """Return an explicitly requested report or the newest available quarter.

    Empty report periods are skipped; transport, schema, and validation errors
    are not treated as missing data. Automatic lookup is bounded by the first
    full quarter using the repository's SW2021 industry classification.
    """
    get_rows = fetcher or fetch_cninfo_report
    if report_date is not None and str(report_date).strip():
        requested = parse_report_date(report_date)
        rows = _validated_records(get_rows(requested), requested)
        if not rows:
            raise ReportUnavailableError(f"no CNINFO holdings disclosure found for {requested.isoformat()}")
        return requested, rows

    today = as_of or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    for candidate in _quarter_ends(today):
        rows = _validated_records(get_rows(candidate), candidate)
        if rows:
            return candidate, rows
    raise ReportUnavailableError(
        f"no CNINFO holdings disclosure found from {MIN_REPORT_DATE.isoformat()} through {today.isoformat()}"
    )


def _plain_records(value: Any) -> list[dict[str, Any]]:
    return rows_from_frame(value)


def _normalize_code(value: Any) -> str:
    if value is None:
        return ""
    numeric_source = isinstance(value, Integral) or isinstance(value, float)
    token = str(value).strip()
    if token.endswith(".0") and token[:-2].isdigit():
        token = token[:-2]
        numeric_source = True
    if token.isdigit() and len(token) == 6:
        return token
    if numeric_source and token.isdigit() and len(token) < 6:
        return token.zfill(6)
    return token


def is_repository_a_share(code: str) -> bool:
    """The repository's taxonomy covers Shanghai/Shenzhen A shares, not BSE."""
    return len(code) == 6 and code.isdigit() and code.startswith(A_SHARE_PREFIXES)


def _normalize_sw_code(value: Any) -> str:
    if value is None:
        return ""
    token = str(value).strip()
    if token.lower() in {"nan", "nat", "none", "<na>"}:
        return ""
    if token.endswith(".0") and token[:-2].isdigit():
        token = token[:-2]
    return token.zfill(6) if token.isdigit() and len(token) <= 6 else token


def _l2_from_sw_code(industry_code: Any, taxonomy: Taxonomy) -> str | None:
    code = _normalize_sw_code(industry_code)
    if code in taxonomy.l2_by_code:
        return code
    # SW classification history contains L3 leaf codes; the repository's tree
    # stops at L2, whose code is the same four-digit family plus "00".
    if re.fullmatch(r"\d{6}", code):
        parent = code[:4] + "00"
        if parent in taxonomy.l2_by_code:
            return parent
    return None


def _date_for_history(value: Any) -> date | None:
    return _parse_row_date(value)


def build_classification_asof(
    history: Any,
    report_date: str | date,
    taxonomy: Taxonomy,
    *,
    wanted_codes: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Map stock codes to the latest SW2021 L2 effective on report_date.

    SW's public history file provides per-stock ``start_date`` and industry code.
    L3 codes roll up to their L2 parent. Any unmapped security stays quarantined.
    """
    target_date = parse_report_date(report_date)
    records = _plain_records(history)
    latest: dict[str, tuple[date, date, str]] = {}
    for row in records:
        code = _normalize_code(row.get("symbol"))
        if not code or (wanted_codes is not None and code not in wanted_codes):
            continue
        start_date = _date_for_history(row.get("start_date"))
        if start_date is None or start_date > target_date:
            continue
        industry = _normalize_sw_code(row.get("industry_code"))
        update_date = _date_for_history(row.get("update_time")) or start_date
        candidate = (start_date, update_date, industry)
        previous = latest.get(code)
        if previous is None or candidate[:2] > previous[:2]:
            latest[code] = candidate
        elif candidate[:2] == previous[:2] and candidate[2] != previous[2]:
            raise FundIndustryError(
                f"ambiguous SW classification for {code} on {start_date.isoformat()}"
            )

    result: dict[str, dict[str, str]] = {}
    for stock_code, (_start, _updated, industry) in latest.items():
        l2_code = _l2_from_sw_code(industry, taxonomy)
        if l2_code is None:
            continue
        l2 = taxonomy.l2_by_code[l2_code]
        result[stock_code] = {"l2_code": l2_code, "l1_id": str(l2["l1_id"])}
    return result


def fetch_sw_classification_history() -> Any:
    """Download SW's public history XLS with a verified, pinned chain supplement."""
    url = "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
    }

    def call() -> Any:
        from urllib.parse import urlsplit

        with verified_sws_ca_bundle() as ca_bundle:
            response = requests.get(
                url,
                headers=headers,
                timeout=(10, 60),
                verify=str(ca_bundle),
            )
        parsed_url = urlsplit(response.url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "www.swsresearch.com":
            raise FundIndustryError(
                f"unexpected redirect target for SW classification: {response.url}"
            )
        response.raise_for_status()
        frame = pd.read_excel(
            io.BytesIO(response.content), dtype={"股票代码": "str", "行业代码": "str"}
        )
        frame.rename(
            columns={
                "股票代码": "symbol",
                "计入日期": "start_date",
                "行业代码": "industry_code",
                "更新日期": "update_time",
            },
            inplace=True,
        )
        frame["start_date"] = pd.to_datetime(frame["start_date"], errors="coerce").dt.date
        frame["update_time"] = pd.to_datetime(frame["update_time"], errors="coerce").dt.date
        return frame

    return _call_with_retry(
        call,
        limiter=_RateLimiter(per_second=1.0),
        attempts=3,
        backoffs=(2, 5),
        desc="SW2021 stock-industry history",
    )


def _decimal(value: Any, *, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"missing numeric value for {field}")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid numeric value for {field}: {value!r}") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"invalid non-negative value for {field}: {value!r}")
    return number


def _rounded(value: Decimal, places: str = "0.01") -> float:
    return float(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _yi(value_wan: Decimal) -> float:
    return _rounded(value_wan / WAN_TO_YI)


def _percentage(value: Decimal, denominator: Decimal) -> float:
    if denominator <= 0:
        return 0.0
    return _rounded(value * Decimal(100) / denominator, "0.0001")


def aggregate_report(
    records: Iterable[Mapping[str, Any]],
    classification: Mapping[str, Mapping[str, str]],
    taxonomy: Taxonomy,
    *,
    l1_id: str,
    l2_code: str,
    report_date: str | date,
) -> dict[str, Any]:
    """Aggregate reported market value by L1/L2 and compute explicit shares.

    All market values are initially in CNINFO's native 10k-CNY field. The
    proportion denominator is the sum of mapped, repo-scope A-share positions,
    not fund NAV, net assets, or other asset classes.
    """
    period = parse_report_date(report_date)
    l1 = taxonomy.l1_by_id[l1_id]
    l2 = taxonomy.l2_by_code[l2_code]
    if l2["l1_id"] != l1_id:
        raise ValueError(f"L2 {l2_code} is not a child of {l1_id}")

    source_total = Decimal(0)
    source_rows = 0
    values_by_stock: dict[str, Decimal] = defaultdict(Decimal)
    for row in records:
        value = _decimal(row.get("持股总市值"), field="持股总市值")
        source_total += value
        source_rows += 1
        stock_code = _normalize_code(row.get("股票代码"))
        if stock_code:
            values_by_stock[stock_code] += value

    in_scope_total = Decimal(0)
    mapped_total = Decimal(0)
    out_of_scope_total = Decimal(0)
    unmapped_total = Decimal(0)
    l1_total = Decimal(0)
    l2_total = Decimal(0)
    in_scope_stocks = 0
    mapped_stocks = 0
    unmapped_stocks = 0
    out_of_scope_stocks = 0

    for stock_code, value in values_by_stock.items():
        if not is_repository_a_share(stock_code):
            out_of_scope_total += value
            out_of_scope_stocks += 1
            continue
        in_scope_total += value
        in_scope_stocks += 1
        assigned = classification.get(stock_code)
        if not assigned or assigned.get("l2_code") not in taxonomy.l2_by_code:
            unmapped_total += value
            unmapped_stocks += 1
            continue
        mapped_l2_code = str(assigned["l2_code"])
        mapped_l1_id = taxonomy.l2_by_code[mapped_l2_code]["l1_id"]
        if assigned.get("l1_id") and assigned["l1_id"] != mapped_l1_id:
            raise FundIndustryError(f"inconsistent L1/L2 classification for stock {stock_code}")
        mapped_total += value
        mapped_stocks += 1
        if mapped_l1_id == l1_id:
            l1_total += value
        if mapped_l2_code == l2_code:
            l2_total += value

    if source_total <= 0 or mapped_total <= 0:
        raise FundIndustryError("CNINFO report has no positive mapped A-share holdings to use as denominator")

    quarter = (period.month, period.day)
    if quarter in {(3, 31), (9, 30)}:
        report_type = "quarterly"
        disclosure_note = (
            "一季度/三季度报告通常只列示每只基金股票投资的前十名；本结果是公开披露明细的合计，"
            "不可解释为全部股票仓位。"
        )
    elif quarter == (6, 30):
        report_type = "semiannual"
        disclosure_note = "中期报告期；按公开定期报告持仓明细汇总，具体覆盖以源数据为准。"
    else:
        report_type = "annual"
        disclosure_note = "年度报告期；按公开定期报告持仓明细汇总，具体覆盖以源数据为准。"

    try:
        akshare_version = version("akshare")
    except PackageNotFoundError:
        akshare_version = "unknown"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "report_date": period.isoformat(),
        "generated_at_utc": now,
        "data_source": {
            "provider": "巨潮资讯 / CNINFO",
            "dataset": "基金重仓股（按股票聚合）",
            "wrapper": "AkShare",
            "wrapper_version": akshare_version,
            "url": "https://webapi.cninfo.com.cn/#/thematicStatistics",
            "market_value_native_unit": "万元（CNY 10,000）",
            "market_value_output_unit": "亿元（CNY 100,000,000）",
        },
        "taxonomy": {
            "map_version": taxonomy.map_version,
            "standard": "申万2021二级行业 → 仓库自定义一级行业",
            "stock_classification_as_of": period.isoformat(),
            "source": "申万宏源公开个股行业分类变动历史，经 AkShare stock_industry_clf_hist_sw 获取",
            "source_url": "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls",
        },
        "selection": {
            "l1_id": l1_id,
            "l1_name": l1["name"],
            "l2_code": l2_code,
            "l2_name": l2["name"],
        },
        "disclosure": {
            "report_type": report_type,
            "coverage_note": disclosure_note,
            "source_rows_are_market_wide_aggregates_by_stock": True,
        },
        "market_value_亿元": {
            "all_source_reported_stock_positions": _yi(source_total),
            "repository_scope_a_shares": _yi(in_scope_total),
            "sw2021_mapped_a_shares": _yi(mapped_total),
            "unmapped_repository_scope_a_shares": _yi(unmapped_total),
            "out_of_repository_scope_securities": _yi(out_of_scope_total),
            "selected_l1": _yi(l1_total),
            "selected_l2": _yi(l2_total),
        },
        "proportion_pct": {
            "denominator": HISTORY_DENOMINATOR,
            "selected_l1_of_mapped_a_share_holdings": _percentage(l1_total, mapped_total),
            "selected_l2_of_mapped_a_share_holdings": _percentage(l2_total, mapped_total),
            "selected_l2_within_selected_l1": _percentage(l2_total, l1_total),
        },
        "coverage": {
            "source_record_count": source_rows,
            "distinct_source_security_count": len(values_by_stock),
            "repository_scope_a_share_count": in_scope_stocks,
            "mapped_a_share_count": mapped_stocks,
            "unmapped_a_share_count": unmapped_stocks,
            "out_of_repository_scope_security_count": out_of_scope_stocks,
            "mapped_value_pct_of_all_source_rows": _percentage(mapped_total, source_total),
            "mapped_value_pct_of_repository_scope_a_shares": _percentage(mapped_total, in_scope_total),
        },
        "interpretation": [
            "所占比例的分母是本报告期内、仓库覆盖范围中、能映射到申万2021二级行业的沪深A股持仓市值总和；不是基金净资产、基金总资产或全部资产类别。",
            "持仓市值按所有基金对同一股票的已披露市值加总；CNINFO 提供按股票汇总数据，因此不需要下载或保存逐只基金持仓。",
            "北交所、B股及其他不能映射到仓库沪深A股行业树的证券不进入行业比例分母；未映射沪深A股另列金额与覆盖率。",
            disclosure_note,
        ],
    }


def aggregate_all_report(
    records: Iterable[Mapping[str, Any]],
    classification: Mapping[str, Mapping[str, str]],
    taxonomy: Taxonomy,
    *,
    report_date: str | date,
) -> dict[str, Any]:
    """Create one compact snapshot covering every L1 and L2 in the taxonomy."""
    rows = list(records)
    industries: list[dict[str, Any]] = []
    base: dict[str, Any] | None = None
    for l1_id, l1 in taxonomy.l1_by_id.items():
        l2_rows: list[dict[str, Any]] = []
        l1_value = 0.0
        l1_share = 0.0
        for code, l2 in taxonomy.l2_by_code.items():
            if l2["l1_id"] != l1_id:
                continue
            detail = aggregate_report(
                rows,
                classification,
                taxonomy,
                l1_id=l1_id,
                l2_code=code,
                report_date=report_date,
            )
            if base is None:
                base = detail
            values = detail["market_value_亿元"]
            shares = detail["proportion_pct"]
            l1_value = values["selected_l1"]
            l1_share = shares["selected_l1_of_mapped_a_share_holdings"]
            l2_rows.append({
                "code": code,
                "name": l2["name"],
                "market_value_亿元": values["selected_l2"],
                "proportion_pct_of_mapped_a_shares": shares["selected_l2_of_mapped_a_share_holdings"],
                "proportion_pct_within_l1": shares["selected_l2_within_selected_l1"],
            })
        industries.append({
            "l1_id": l1_id,
            "l1_name": l1["name"],
            "market_value_亿元": l1_value,
            "proportion_pct_of_mapped_a_shares": l1_share,
            "level2": l2_rows,
        })
    if base is None:
        raise FundIndustryError("taxonomy contains no industry pairs")
    base["all_industries"] = True
    base["selection"] = {
        "l1_id": "ALL",
        "l1_name": "全部一级行业",
        "l2_code": "ALL",
        "l2_name": "全部二级行业",
    }
    base["market_value_亿元"].pop("selected_l1", None)
    base["market_value_亿元"].pop("selected_l2", None)
    base["proportion_pct"].pop("selected_l1_of_mapped_a_share_holdings", None)
    base["proportion_pct"].pop("selected_l2_of_mapped_a_share_holdings", None)
    base["proportion_pct"].pop("selected_l2_within_selected_l1", None)
    base["industries"] = industries
    return base


def render_markdown(
    summary: Mapping[str, Any], history: Mapping[str, Any] | None = None
) -> str:
    """Create a concise, auditable run report for the Actions summary/artifact."""
    if summary.get("all_industries"):
        values = summary["market_value_亿元"]
        coverage = summary["coverage"]
        source = summary["data_source"]
        lines = [
            f"# 公募基金全行业持仓快照（{summary['report_date']}）",
            "",
            f"- 数据源：[{source['provider']} {source['dataset']}]({source['url']})，经 {source['wrapper']} {source['wrapper_version']} 获取。",
            f"- 报告类型：`{summary['disclosure']['report_type']}`。",
            f"- 分类历史按报告期 `{summary['taxonomy']['stock_classification_as_of']}` 生效记录映射。",
            "",
            "## 总体覆盖",
            "",
            f"- 映射沪深A股持仓市值：**{values['sw2021_mapped_a_shares']:,.2f} 亿元**。",
            f"- 源表 {coverage['source_record_count']:,} 行、{coverage['distinct_source_security_count']:,} 只不同证券；映射金额覆盖源表总额 {coverage['mapped_value_pct_of_all_source_rows']:.4f}%。",
            "",
            "## 两级行业明细",
            "",
            "| 一级行业 | 二级行业 | 持仓市值（亿元） | 占映射沪深A股持仓 | 占一级行业持仓 |",
            "|---|---|---:|---:|---:|",
        ]
        for l1 in summary["industries"]:
            lines.append(
                f"| **{l1['l1_name']}** | **一级合计** | **{l1['market_value_亿元']:,.2f}** | **{l1['proportion_pct_of_mapped_a_shares']:.4f}%** | 100.0000% |"
            )
            for l2 in l1["level2"]:
                lines.append(
                    f"| {l1['l1_name']} | {l2['name']} (`{l2['code']}`) | {l2['market_value_亿元']:,.2f} | {l2['proportion_pct_of_mapped_a_shares']:.4f}% | {l2['proportion_pct_within_l1']:.4f}% |"
                )
        _append_history_comparison(lines, summary, history)
        lines.extend([
            "",
            "**解释限制：**",
            *[f"- {note}" for note in summary["interpretation"]],
            "",
            "持仓明细按 CNINFO 的市场汇总数据处理；不保存逐只基金持仓或原始行。",
            "",
        ])
        return "\n".join(lines)

    selection = summary["selection"]
    values = summary["market_value_亿元"]
    shares = summary["proportion_pct"]
    coverage = summary["coverage"]
    source = summary["data_source"]
    lines = [
        f"# 公募基金行业持仓汇总（{summary['report_date']}）",
        "",
        f"- 一级行业：**{selection['l1_name']}** (`{selection['l1_id']}`)",
        f"- 二级行业：**{selection['l2_name']}** (申万代码 `{selection['l2_code']}`)",
        f"- 数据源：[{source['provider']} {source['dataset']}]({source['url']})，经 {source['wrapper']} {source['wrapper_version']} 获取。",
        f"- 报告类型：`{summary['disclosure']['report_type']}`。",
        "",
        "## 汇总结果",
        "",
        f"- 一级行业持仓市值：**{values['selected_l1']:,.2f} 亿元**（占映射沪深A股持仓 **{shares['selected_l1_of_mapped_a_share_holdings']:.4f}%**）。",
        f"- 二级行业持仓市值：**{values['selected_l2']:,.2f} 亿元**（占映射沪深A股持仓 **{shares['selected_l2_of_mapped_a_share_holdings']:.4f}%**；占所选一级行业 **{shares['selected_l2_within_selected_l1']:.4f}%**）。",
        f"- 比例分母（映射沪深A股股票持仓）：**{values['sw2021_mapped_a_shares']:,.2f} 亿元**；全部源表证券持仓为 {values['all_source_reported_stock_positions']:,.2f} 亿元。",
        "",
        "## 覆盖与口径",
        "",
        f"源表 {coverage['source_record_count']:,} 行、{coverage['distinct_source_security_count']:,} 只不同证券；仓库范围沪深A股 {coverage['repository_scope_a_share_count']:,} 只，其中 {coverage['mapped_a_share_count']:,} 只已映射到申万2021二级行业。映射金额覆盖源表总额 {coverage['mapped_value_pct_of_all_source_rows']:.4f}%，覆盖仓库范围A股金额 {coverage['mapped_value_pct_of_repository_scope_a_shares']:.4f}%。",
        f"未映射沪深A股金额：{values['unmapped_repository_scope_a_shares']:,.2f} 亿元；仓库范围外证券金额：{values['out_of_repository_scope_securities']:,.2f} 亿元。",
        "",
        "**解释限制：**",
    ]
    lines.extend(f"- {note}" for note in summary["interpretation"])
    lines.extend([
        "",
        "市场市值单位由 CNINFO 原始字段“万元”换算为“亿元”；原始记录和逐只基金明细不会写入仓库。",
        "",
    ])
    return "\n".join(lines)


HISTORY_SCHEMA_VERSION = 1
def _history_period(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only aggregate, auditable per-quarter data; never fund-level rows."""
    if not summary.get("all_industries"):
        raise ValueError("quarter history can only be updated by a full-industry snapshot")
    l2_rows = [
        {
            "l1_id": l1["l1_id"],
            "l1_name": l1["l1_name"],
            "code": l2["code"],
            "name": l2["name"],
            "market_value_亿元": l2["market_value_亿元"],
            "proportion_pct_of_mapped_a_shares": l2[
                "proportion_pct_of_mapped_a_shares"
            ],
            "proportion_pct_within_l1": l2["proportion_pct_within_l1"],
        }
        for l1 in summary["industries"]
        for l2 in l1["level2"]
    ]
    codes = [row["code"] for row in l2_rows]
    if len(l2_rows) != 134 or len(set(codes)) != 134:
        raise ValueError(
            f"full-industry history requires 134 unique L2 rows; found {len(set(codes))}"
        )
    values = summary["market_value_亿元"]
    coverage = summary["coverage"]
    return {
        "report_date": parse_report_date(summary["report_date"]).isoformat(),
        "generated_at_utc": summary["generated_at_utc"],
        "report_type": summary["disclosure"]["report_type"],
        "disclosure_note": summary["disclosure"]["coverage_note"],
        "market_value_亿元": {
            "all_source_reported_stock_positions": values[
                "all_source_reported_stock_positions"
            ],
            "repository_scope_a_shares": values["repository_scope_a_shares"],
            "sw2021_mapped_a_shares": values["sw2021_mapped_a_shares"],
            "unmapped_repository_scope_a_shares": values[
                "unmapped_repository_scope_a_shares"
            ],
            "out_of_repository_scope_securities": values[
                "out_of_repository_scope_securities"
            ],
        },
        "coverage": dict(coverage),
        "industries": l2_rows,
    }


def build_quarter_history(
    summary: Mapping[str, Any], history_path: str | Path
) -> dict[str, Any]:
    """Upsert a complete quarterly snapshot, replacing corrections idempotently."""
    taxonomy = summary["taxonomy"]
    if history_path and Path(history_path).exists():
        previous = json.loads(Path(history_path).read_text(encoding="utf-8"))
        if previous.get("schema_version") != HISTORY_SCHEMA_VERSION:
            raise ValueError("unsupported fund-industry history schema version")
        if previous.get("taxonomy", {}).get("map_version") != taxonomy["map_version"]:
            raise ValueError("history taxonomy version differs; refusing to mix industry maps")
        if previous.get("proportion_denominator") != HISTORY_DENOMINATOR:
            raise ValueError("history proportion denominator differs; refusing to mix metrics")
        periods = previous.get("periods")
        if not isinstance(periods, list):
            raise ValueError("history periods must be a list")
        seen_dates: set[str] = set()
        expected_codes: set[str] | None = None
        for period in periods:
            period_date = parse_report_date(period.get("report_date", "")).isoformat()
            if period_date in seen_dates:
                raise ValueError(f"history contains duplicate report date {period_date}")
            seen_dates.add(period_date)
            rows = period.get("industries")
            if not isinstance(rows, list) or len(rows) != 134:
                raise ValueError("existing history period must contain all 134 L2 industries")
            codes = {row.get("code") for row in rows}
            if len(codes) != 134:
                raise ValueError("existing history period contains duplicate L2 codes")
            if expected_codes is None:
                expected_codes = codes
            elif codes != expected_codes:
                raise ValueError("history periods contain different L2 code sets")
        history = previous
    else:
        history = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "taxonomy": {
                "map_version": taxonomy["map_version"],
                "standard": taxonomy["standard"],
            },
            "units": {"market_value": "亿元", "proportion": "%"},
            "proportion_denominator": HISTORY_DENOMINATOR,
            "periods": [],
        }

    current = _history_period(summary)
    current_codes = {row["code"] for row in current["industries"]}
    if history["periods"] and current_codes != {
        row["code"] for row in history["periods"][0]["industries"]
    }:
        raise ValueError("current snapshot L2 code set differs from saved history")
    keyed = {period["report_date"]: period for period in history["periods"]}
    keyed[current["report_date"]] = current
    history["periods"] = [keyed[period] for period in sorted(keyed)]
    return history


def _append_history_comparison(
    lines: list[str],
    summary: Mapping[str, Any],
    history: Mapping[str, Any] | None,
) -> None:
    if history is None:
        return
    current_date = summary["report_date"]
    prior = next(
        (
            period
            for period in reversed(history["periods"])
            if period["report_date"] < current_date
        ),
        None,
    )
    lines.extend(["", "## 与上一已留存报告期比较", ""])
    if prior is None:
        lines.extend([
            "这是历史库中的首个报告期，目前没有更早季度可供比较。",
            "",
        ])
        return
    prior_rows = {row["code"]: row for row in prior["industries"]}
    lines.extend([
        f"本期 `{current_date}` 对比上一已留存报告期 `{prior['report_date']}`；若中间有季度未成功披露或运行，前后两期不一定是相邻日历季度。",
        "",
        "| 一级行业 | 二级行业 | 本期市值（亿元） | 上期市值（亿元） | 市值变化（亿元） | 本期占比 | 上期占比 | 占比变化（百分点） |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for l1 in summary["industries"]:
        for l2 in l1["level2"]:
            previous = prior_rows[l2["code"]]
            value_delta = l2["market_value_亿元"] - previous["market_value_亿元"]
            share_delta = (
                l2["proportion_pct_of_mapped_a_shares"]
                - previous["proportion_pct_of_mapped_a_shares"]
            )
            lines.append(
                f"| {l1['l1_name']} | {l2['name']} (`{l2['code']}`) | "
                f"{l2['market_value_亿元']:,.2f} | {previous['market_value_亿元']:,.2f} | "
                f"{value_delta:+,.2f} | {l2['proportion_pct_of_mapped_a_shares']:.4f}% | "
                f"{previous['proportion_pct_of_mapped_a_shares']:.4f}% | {share_delta:+.4f} |"
            )
    lines.append("")


def render_trend_html(history: Mapping[str, Any]) -> str:
    """Render a dependency-free dashboard with selectable L2 value/share charts."""
    periods = history["periods"]
    if not periods:
        raise ValueError("cannot render a trend chart without saved report periods")
    latest = periods[-1]
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for item in latest["industries"]:
        groups.setdefault((item["l1_id"], item["l1_name"]), []).append(item)
    options = []
    for (_l1_id, l1_name), items in groups.items():
        options.append(f'<optgroup label="{html.escape(l1_name, quote=True)}">')
        for item in items:
            label = f"{item['name']} ({item['code']})"
            options.append(
                f'<option value="{html.escape(item["code"], quote=True)}">'
                f"{html.escape(label)}</option>"
            )
        options.append("</optgroup>")
    serialized = json.dumps(history, ensure_ascii=False, separators=(",", ":"))
    serialized = serialized.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    date_list = "、".join(html.escape(period["report_date"]) for period in periods)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>公募基金二级行业持仓趋势</title>
<style>
body{{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;color:#172033;max-width:1120px;margin:24px auto;padding:0 18px;background:#f7f9fc}}
h1{{margin-bottom:4px}} .muted{{color:#526174}} .notice{{padding:12px 16px;background:#fff6dc;border-left:4px solid #d39b18;margin:18px 0}}
.panel{{background:white;border:1px solid #dce3ed;border-radius:10px;padding:16px;margin:16px 0;box-shadow:0 2px 7px #14213d0a}}
label{{font-weight:650}} select{{font:inherit;padding:8px 10px;max-width:100%;margin-left:8px}} svg{{width:100%;height:auto;display:block}} .chart-title{{font-size:18px;font-weight:700}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid #e5eaf1}} th{{background:#f1f5fa;position:sticky;top:0}}
.table-wrap{{overflow:auto;max-height:520px}} .legend{{color:#526174;font-size:14px}} code{{white-space:nowrap}}
</style></head><body>
<h1>公募基金二级行业持仓趋势</h1>
<p id="period-summary" class="muted"></p>
<details class="panel"><summary>已保存的全部报告期</summary><p>{date_list}</p></details>
<div class="notice"><strong>披露与口径提示：</strong>一季度、三季度报告通常只列每只基金股票投资的前十名；行业值是 CNINFO 已公开持仓明细的合计，不代表全部股票仓位。占比以当期已映射到申万2021二级行业的沪深A股持仓市值总和为分母，不是基金净资产、基金总资产或全部资产类别；北交所、B股、仓库外及未映射证券不进入该分母。下表逐期展示映射覆盖率和披露类型，判断趋势时请一并查看。</div>
<section class="panel"><label for="industry">选择二级行业：</label><select id="industry">{''.join(options)}</select>
<p id="selected-label" class="muted"></p>
<h2 class="chart-title">持仓市值（亿元）</h2><svg id="value-chart" role="img" aria-label="所选二级行业持仓市值时间序列图"></svg>
<h2 class="chart-title">占映射沪深A股持仓比例（%）</h2><svg id="share-chart" role="img" aria-label="所选二级行业持仓比例时间序列图"></svg>
<p class="legend">两个指标分图绘制、各自使用纵轴；悬停数据点可查看完整报告期日期。</p></section>
<section class="panel"><h2>逐期数据与覆盖情况</h2><div class="table-wrap"><table><thead><tr><th>报告期</th><th>持仓市值（亿元）</th><th>占映射持仓</th><th>占一级行业</th><th>报告类型</th><th>源表映射覆盖率</th><th>披露说明</th></tr></thead><tbody id="history-rows"></tbody></table></div></section>
<script>
const HISTORY = {serialized};
const SVG_NS = "http://www.w3.org/2000/svg";
const rowsFor = code => HISTORY.periods.map(period => ({{period, item: period.industries.find(row => row.code === code)}}));
function svgNode(tag, attributes={{}}) {{ const node=document.createElementNS(SVG_NS,tag); for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,String(value)); return node; }}
function drawChart(id, points, key, color, unit) {{
  const svg=document.getElementById(id); svg.replaceChildren(); svg.setAttribute("viewBox","0 0 960 330");
  const W=960,H=330,m={{left:76,right:20,top:20,bottom:54}},pw=W-m.left-m.right,ph=H-m.top-m.bottom;
  const vals=points.map(p=>Number(p.item[key])); const topRaw=Math.max(...vals,0); const top=topRaw===0?1:Math.ceil(topRaw*1.12/4)*4;
  for(let i=0;i<=4;i++) {{ const y=m.top+ph*i/4, val=top*(4-i)/4; svg.append(svgNode("line",{{x1:m.left,y1:y,x2:W-m.right,y2:y,stroke:"#e3e9f1"}})); const t=svgNode("text",{{x:m.left-10,y:y+5,"text-anchor":"end",fill:"#526174","font-size":12}}); t.textContent=val.toFixed(unit==="%"?2:1); svg.append(t); }}
  const x=i=>m.left+(points.length<2?pw/2:i*pw/(points.length-1)); const y=v=>m.top+ph-(v/top)*ph;
  const path=svgNode("path",{{d:vals.map((v,i)=>`${{i===0?"M":"L"}}${{x(i).toFixed(1)}} ${{y(v).toFixed(1)}}`).join(" "),fill:"none",stroke:color,"stroke-width":3,"stroke-linejoin":"round","stroke-linecap":"round"}}); svg.append(path);
  const labelIndexes=new Set([0,points.length-1]); for(let i=0;i<points.length;i+=Math.max(1,Math.ceil(points.length/7))) labelIndexes.add(i);
  points.forEach((p,i)=>{{ const c=svgNode("circle",{{cx:x(i),cy:y(vals[i]),r:4,fill:color,stroke:"white","stroke-width":1.5}}); const title=svgNode("title"); title.textContent=`${{p.period.report_date}}: ${{vals[i].toFixed(unit==="%"?4:2)}} ${{unit}}`; c.append(title); svg.append(c); if(labelIndexes.has(i)){{const t=svgNode("text",{{x:x(i),y:H-22,"text-anchor":"middle",fill:"#526174","font-size":11}});t.textContent=p.period.report_date.slice(0,7);svg.append(t);}} }});
  const yLabel=svgNode("text",{{x:18,y:m.top+ph/2,transform:`rotate(-90 18 ${{m.top+ph/2}})`,fill:"#526174","font-size":12,"text-anchor":"middle"}}); yLabel.textContent=unit; svg.append(yLabel);
}}
function render() {{
  const code=document.getElementById("industry").value, points=rowsFor(code), latest=points[points.length-1];
  document.getElementById("selected-label").textContent=`${{latest.item.l1_name}} · ${{latest.item.name}}（申万代码 ${{code}}）`;
  drawChart("value-chart",points,"market_value_亿元","#2463eb","亿元");
  drawChart("share-chart",points,"proportion_pct_of_mapped_a_shares","#c2410c","%");
  const body=document.getElementById("history-rows"); body.replaceChildren();
  points.forEach(({{period,item}})=>{{const tr=document.createElement("tr"); const values=[period.report_date,Number(item.market_value_亿元).toFixed(2),Number(item.proportion_pct_of_mapped_a_shares).toFixed(4)+"%",Number(item.proportion_pct_within_l1).toFixed(4)+"%",period.report_type,Number(period.coverage.mapped_value_pct_of_all_source_rows).toFixed(4)+"%",period.disclosure_note]; for(const value of values){{const td=document.createElement("td");td.textContent=value;tr.append(td);}}body.append(tr);}});
}}
const first=HISTORY.periods[0], last=HISTORY.periods[HISTORY.periods.length-1];
document.getElementById("period-summary").textContent=`最新报告期：${{last.report_date}}；历史范围：${{first.report_date}} 至 ${{last.report_date}}，共 ${{HISTORY.periods.length}} 个已保存报告期。`;
document.getElementById("industry").addEventListener("change",render); render();
</script></body></html>'''


def write_report_files(summary: Mapping[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    """Persist aggregate output; full snapshots also update history and trend chart."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    selection = summary["selection"]
    report_key = (
        f"{summary['report_date'].replace('-', '')}__{selection['l1_id']}__"
        f"{selection['l2_code']}"
    )
    json_path = target / f"{report_key}.json"
    markdown_path = target / f"{report_key}.md"
    history_path: Path | None = None
    chart_path: Path | None = None
    history: dict[str, Any] | None = None
    if summary.get("all_industries"):
        history_path = target / "history.json"
        chart_path = target / "trend.html"
        history = build_quarter_history(summary, history_path)
        history_tmp = history_path.with_suffix(".json.tmp")
        chart_tmp = chart_path.with_suffix(".html.tmp")
        history_tmp.write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        chart_tmp.write_text(render_trend_html(history), encoding="utf-8")
        os.replace(history_tmp, history_path)
        os.replace(chart_tmp, chart_path)
    json_tmp = json_path.with_suffix(".json.tmp")
    md_tmp = markdown_path.with_suffix(".md.tmp")
    json_tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_tmp.write_text(render_markdown(summary, history), encoding="utf-8")
    os.replace(json_tmp, json_path)
    os.replace(md_tmp, markdown_path)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"report_json={json_path.as_posix()}\n")
            handle.write(f"report_markdown={markdown_path.as_posix()}\n")
            if history_path and chart_path:
                handle.write(f"report_history={history_path.as_posix()}\n")
                handle.write(f"report_chart={chart_path.as_posix()}\n")
    return json_path, markdown_path

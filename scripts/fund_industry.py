"""Aggregate public-fund stock holdings by the repository's SW2021 taxonomy.

The source returns market-wide holdings aggregated by stock, so individual fund
holdings are never persisted. Values are kept in the source-native unit (10k CNY)
for arithmetic and rendered in 100m CNY (亿元).
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from importlib.metadata import PackageNotFoundError, version
from numbers import Integral
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import yaml

from scripts.common.http import RateLimiter, call_with_retry

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY = ROOT / "config" / "taxonomy" / "sw2021_repository_tree.yaml"
MIN_REPORT_DATE = date(2021, 9, 30)  # first full quarter after SW2021 took effect
CNINFO_FIELDS = ("股票代码", "报告期", "持股总市值")
A_SHARE_PREFIXES = (
    "000", "001", "002", "003", "300", "301",
    "600", "601", "603", "605", "688", "689",
)
WAN_TO_YI = Decimal("10000")  # 10,000 x 万元 = 1 亿元


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

    frame = call_with_retry(
        call,
        limiter=RateLimiter(per_second=2.0),
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
    """Download SW's public historical stock-classification file via AkShare."""
    import akshare as ak

    return call_with_retry(
        ak.stock_industry_clf_hist_sw,
        limiter=RateLimiter(per_second=1.0),
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
            "denominator": "all SW2021-mapped Shanghai/Shenzhen A-share stock positions in this CNINFO report period across funds",
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


def render_markdown(summary: Mapping[str, Any]) -> str:
    """Create a concise, auditable run report for the Actions summary/artifact."""
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


def write_report_files(summary: Mapping[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    """Persist only the small aggregate snapshot and its Markdown explanation."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    selection = summary["selection"]
    report_key = (
        f"{summary['report_date'].replace('-', '')}__{selection['l1_id']}__"
        f"{selection['l2_code']}"
    )
    json_path = target / f"{report_key}.json"
    markdown_path = target / f"{report_key}.md"
    json_tmp = json_path.with_suffix(".json.tmp")
    md_tmp = markdown_path.with_suffix(".md.tmp")
    json_tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_tmp.write_text(render_markdown(summary), encoding="utf-8")
    os.replace(json_tmp, json_path)
    os.replace(md_tmp, markdown_path)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"report_json={json_path.as_posix()}\n")
            handle.write(f"report_markdown={markdown_path.as_posix()}\n")
    return json_path, markdown_path

"""Pure markdown digests from trend.db (ops §5.2)."""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable, Optional, Sequence

from scripts.common.taxonomy_meta import L1Bucket, load_l1_buckets
from scripts.common.universe import load_l2_to_l1, load_stock_sw_l2
from scripts.metrics.temp_raw import rank


def _td(value: Any) -> str:
    return str(value)


def _fmt_amount_yi(v: Any) -> str:
    if v is None:
        return ""
    return "%.3f" % (float(v) / 1e8)


def _stock_name_map() -> dict[str, str]:
    return {r["ts_code"]: (r.get("name_zh") or "") for r in load_stock_sw_l2()}


def _l2_name_map() -> dict[str, str]:
    return {r["code"]: (r.get("name_zh") or "") for r in load_l2_to_l1()}


def _run_link(sha: Optional[str]) -> str:
    server = (os.environ.get("GITHUB_SERVER_URL") or "").rstrip("/")
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    run_id = (os.environ.get("GITHUB_RUN_ID") or "").strip()
    if server and repo and run_id:
        return "%s/%s/actions/runs/%s" % (server, repo, run_id)
    return sha or ""


def _hottest_t(values: Iterable[Optional[str]]) -> Optional[str]:
    best: Optional[str] = None
    best_r: Optional[int] = None
    for t in values:
        if not t:
            continue
        try:
            r = rank(t)
        except ValueError:
            continue
        if best_r is None or r > best_r:
            best, best_r = t, r
    return best


def _meta_header(conn: sqlite3.Connection, trade_date: str, title: str) -> list[str]:
    row = conn.execute(
        """
        SELECT param_version, map_version, status, git_sha
        FROM run_meta WHERE trade_date=?
        """,
        (trade_date,),
    ).fetchone()
    if row:
        param, map_v, status, sha = row
    else:
        param = map_v = status = sha = None
    run = _run_link(sha)
    return [
        "# %s · %s" % (title, trade_date),
        "",
        "meta: as_of=%s param=%s map=%s status=%s run=%s"
        % (trade_date, param or "—", map_v or "—", status or "—", run or "—"),
        "",
    ]


def _l2_codes_for_l1(conn: sqlite3.Connection, trade_date: str, l1_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT sw_l2_code
        FROM daily_stock
        WHERE trade_date=? AND l1_id=?
          AND sw_l2_code IS NOT NULL AND TRIM(sw_l2_code) != ''
        """,
        (trade_date, l1_id),
    ).fetchall()
    return [str(r[0]) for r in rows]


def _sort_l2_key(row: tuple) -> tuple:
    # row: code, T, S_temp, RS, right_side, tag_warm_to_hot, solar_term,
    #      warm_to_hot_member_count, amount
    t = row[1]
    try:
        r = rank(t) if t else -99
    except ValueError:
        r = -99
    s = row[2] if row[2] is not None else float("-inf")
    return (-r, -float(s))


def _fmt_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return "%.4g" % v
    return str(v)


def _md_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    any_row = False
    for row in rows:
        any_row = True
        lines.append("| " + " | ".join(_fmt_cell(c) for c in row) + " |")
    if not any_row:
        lines.append("| " + " | ".join("" for _ in headers) + " |")
    return lines


def render_l1_issue(
    conn: sqlite3.Connection,
    trade_date: str,
    l1_id: str,
    *,
    name_zh: str,
    top_n: int = 20,
) -> str:
    td = _td(trade_date)
    lines = _meta_header(conn, td, name_zh)
    stock_names = _stock_name_map()
    l2_names = _l2_name_map()

    l2_codes = _l2_codes_for_l1(conn, td, l1_id)
    l2_rows: list[tuple] = []
    if l2_codes:
        qmarks = ",".join("?" * len(l2_codes))
        l2_rows = list(
            conn.execute(
                """
                SELECT code, T, S_temp, RS, right_side, tag_warm_to_hot,
                       solar_term, warm_to_hot_member_count, amount
                FROM daily_l2
                WHERE trade_date=? AND code IN (%s)
                """
                % qmarks,
                (td, *l2_codes),
            ).fetchall()
        )
    l2_rows.sort(key=_sort_l2_key)

    lines.append("## L1 自身")
    row = conn.execute(
        """
        SELECT T, RS, right_side, solar_term, tag_warm_to_hot,
               warm_to_hot_member_count, amount
        FROM daily_l1 WHERE trade_date=? AND code=?
        """,
        (td, l1_id),
    ).fetchone()
    headers = ["T", "l1_id", "名称", "RS", "右侧", "节气", "温转热", "成分温转热", "成交额(亿)"]
    if row is None:
        cells = ["", l1_id, name_zh, "", "", "", "", "", ""]
    else:
        t, rs, right, solar, tag, wcount, amt = row
        cells = [
            "" if t is None else t,
            l1_id,
            name_zh,
            "" if rs is None else rs,
            "" if right is None else right,
            "" if solar is None else solar,
            "" if tag is None else tag,
            0 if wcount is None else wcount,
            _fmt_amount_yi(amt),
        ]
    lines.extend(_md_table(headers, [tuple(cells)]))
    lines.append("")

    lines.append("## 行业（L2）扫描")
    lines.extend(
        _md_table(
            ["T", "代码", "名称", "RS", "右侧", "节气", "温转热", "成分温转热", "成交额(亿)"],
            [
                (
                    r[1],
                    r[0],
                    l2_names.get(str(r[0]), ""),
                    r[3],
                    r[4],
                    r[6],
                    r[5],
                    r[7],
                    _fmt_amount_yi(r[8]),
                )
                for r in l2_rows
            ],
        )
    )
    lines.append("")

    hot = conn.execute(
        """
        SELECT ts_code, T, RS, right_side, solar_term, amount
        FROM daily_stock
        WHERE trade_date=? AND l1_id=? AND IFNULL(tag_warm_to_hot,0)=1
        ORDER BY IFNULL(amount,0) DESC
        LIMIT ?
        """,
        (td, l1_id, top_n),
    ).fetchall()
    lines.append("## 今日温转热（个股，Top N by 成交额）")
    lines.extend(
        _md_table(
            ["ts_code", "名称", "T", "RS", "右侧", "节气", "成交额(亿)"],
            [
                (r[0], stock_names.get(str(r[0]), ""), r[1], r[2], r[3], r[4], _fmt_amount_yi(r[5]))
                for r in hot
            ],
        )
    )
    lines.append("")

    exits = conn.execute(
        """
        SELECT ts_code, event, T, detail
        FROM signal_event
        WHERE trade_date=? AND l1_id=? AND superseded_by IS NULL
          AND event='EXIT_RIGHT'
        ORDER BY event, ts_code
        """,
        (td, l1_id),
    ).fetchall()
    lines.append("## 今日温转平 / 结束右侧")
    lines.extend(
        _md_table(
            ["ts_code", "名称", "event", "T", "detail"],
            [
                (r[0], stock_names.get(str(r[0]), ""), r[1], r[2], r[3])
                for r in exits
            ],
        )
    )
    lines.append("")

    right = conn.execute(
        """
        SELECT ts_code, T, RS, solar_term, right_side_days_trading, amount
        FROM daily_stock
        WHERE trade_date=? AND l1_id=? AND IFNULL(right_side,0)=1
        ORDER BY IFNULL(RS, -1e99) DESC, IFNULL(amount,0) DESC
        LIMIT ?
        """,
        (td, l1_id, top_n),
    ).fetchall()
    lines.append("## 右侧存续 Top（RS 高）")
    lines.extend(
        _md_table(
            ["ts_code", "名称", "T", "RS", "节气", "交易日天数", "成交额(亿)"],
            [
                (r[0], stock_names.get(str(r[0]), ""), r[1], r[2], r[3], r[4], _fmt_amount_yi(r[5]))
                for r in right
            ],
        )
    )
    lines.append("")
    return "\n".join(lines)


def render_radar_issue(
    conn: sqlite3.Connection,
    trade_date: str,
    buckets: Optional[Sequence[L1Bucket]] = None,
    *,
    top_n: int = 20,
) -> str:
    td = _td(trade_date)
    buckets = list(buckets) if buckets is not None else load_l1_buckets()
    lines = _meta_header(conn, td, "A股战场")

    tot = conn.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN IFNULL(right_side,0)=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN IFNULL(tag_warm_to_hot,0)=1 THEN 1 ELSE 0 END)
        FROM daily_stock WHERE trade_date=?
        """,
        (td,),
    ).fetchone()
    n_all, n_right, n_hot = (tot[0] or 0), (tot[1] or 0), (tot[2] or 0)
    ratio = (float(n_right) / float(n_all)) if n_all else 0.0
    lines.append("## 总览")
    lines.append(
        "- 个股数=%d 右侧=%d (%.1f%%) 温转热=%d"
        % (n_all, n_right, 100.0 * ratio, n_hot)
    )
    lines.append("")

    l1_table: list[tuple] = []
    for b in buckets:
        row = conn.execute(
            """
            SELECT T,
                   SUM(CASE WHEN IFNULL(right_side,0)=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN IFNULL(tag_warm_to_hot,0)=1 THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM daily_stock WHERE trade_date=? AND l1_id=?
            GROUP BY T
            """,
            (td, b.l1_id),
        ).fetchall()
        c = sum(int(x[3] or 0) for x in row)
        rgt = sum(int(x[1] or 0) for x in row)
        h = sum(int(x[2] or 0) for x in row)
        t = _hottest_t(x[0] for x in row)
        share = (float(rgt) / float(c)) if c else 0.0
        l1_table.append((b.name_zh, b.l1_id, t, c, rgt, share, h))
    l1_table.sort(key=lambda x: (-x[5], -x[6], x[1]))

    lines.append("## 按 L1")
    lines.extend(
        _md_table(
            ["L1", "l1_id", "T*", "个股", "右侧", "右侧占比", "个股温转热"],
            [
                (name, lid, t, c, r, "%.1f%%" % (100.0 * share), h)
                for name, lid, t, c, r, share, h in l1_table
            ],
        )
    )
    lines.append("")
    lines.append(
        "T* / 个股温转热 = 个股截面（按 l1_id），非 L1 同引擎；"
        "L1 自身（含 YAML 闭包「成分温转热」）见各 L1 Issue「L1 自身」。"
    )
    lines.append("")
    lines.append("## 全市场温转热 Top（成交额）")
    stock_names = _stock_name_map()
    hot = conn.execute(
        """
        SELECT ts_code, l1_id, T, RS, amount
        FROM daily_stock
        WHERE trade_date=? AND IFNULL(tag_warm_to_hot,0)=1
        ORDER BY IFNULL(amount,0) DESC
        LIMIT ?
        """,
        (td, top_n),
    ).fetchall()
    lines.extend(
        _md_table(
            ["ts_code", "名称", "l1_id", "T", "RS", "成交额(亿)"],
            [
                (r[0], stock_names.get(str(r[0]), ""), r[1], r[2], r[3], _fmt_amount_yi(r[4]))
                for r in hot
            ],
        )
    )
    lines.append("")
    return "\n".join(lines)

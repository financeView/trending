from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Sequence, Tuple

from scripts.common.bars import LIMIT_SOURCE_BOARD_CALC
from scripts.common.calendar import prev_trade_date
from scripts.common.ts_code import to_ts_code


def board_pct(ts_code: str, is_st: int) -> float:
    if int(is_st or 0) == 1:
        return 0.05
    num = to_ts_code(ts_code).split(".")[0]
    if num.startswith(("300", "301", "688")):
        return 0.20
    return 0.10


def limit_prices(preclose: float, pct: float) -> Tuple[float, float]:
    base = Decimal(str(preclose))
    p = Decimal(str(pct))
    up = (base * (Decimal("1") + p)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    down = (base * (Decimal("1") - p)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(up), float(down)


def apply_board_calc(
    conn,
    ts_codes: Sequence[str],
    *,
    session_asof: date,
    limit_rule: str,
    commit: bool = True,
) -> int:
    if str(limit_rule) != "board_calc_v1":
        return 0
    n_write = 0
    for ts in ts_codes:
        ts_n = to_ts_code(ts)
        rows = conn.execute(
            """
            SELECT trade_date, close_raw, is_st, limit_up, limit_down
            FROM bars WHERE ts_code=? ORDER BY trade_date ASC
            """,
            (ts_n,),
        ).fetchall()
        by_td = {str(r[0])[:10]: r for r in rows}
        for td_s, close_raw, is_st, up, down in rows:
            td = date.fromisoformat(str(td_s)[:10])
            if td >= session_asof:
                continue
            if up is not None or down is not None:
                continue
            prev = prev_trade_date(td)
            if prev is None:
                continue
            prev_row = by_td.get(prev.isoformat())
            if not prev_row:
                continue
            basis = prev_row[1]  # close_raw of prev
            try:
                basis_f = float(basis)
            except (TypeError, ValueError):
                continue
            if basis_f <= 0 or basis_f != basis_f:
                continue
            pct = board_pct(ts_n, int(is_st or 0))
            lu, ld = limit_prices(basis_f, pct)
            cur = conn.execute(
                """
                UPDATE bars
                SET limit_up=?, limit_down=?, limit_source=?, preclose_raw=?
                WHERE ts_code=? AND trade_date=?
                  AND limit_up IS NULL AND limit_down IS NULL
                """,
                (lu, ld, LIMIT_SOURCE_BOARD_CALC, basis_f, ts_n, td_s),
            )
            n_write += int(cur.rowcount or 0)
    if commit:
        conn.commit()
    return n_write

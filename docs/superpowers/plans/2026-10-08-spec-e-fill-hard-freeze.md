# Spec E: board_calc + hard_freeze_flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable hist-only `board_calc_v1` limits, persist `hard_freeze_flag` from suspend streak N=20, wire `limit_up_unfillable: false` into costs, and make metrics/`daily_run` OR the flag into `hard_frozen`.

**Architecture:** Approach 1 — same sync job after OHLC/flags (and optional EM limits): ensure bars column → hard-freeze full-universe rewrite → hist board_calc pass → then `daily_run`. Fill reads stored `limit_*`; metrics reads stored `hard_freeze_flag` (no engine-side streak/`board_calc` recompute). `session_asof = latest_trade_day()` (or `--asof`), never `--end`.

**Tech Stack:** Python 3.11, SQLite bars.db, PyYAML, Decimal `ROUND_HALF_UP`, pytest, existing sync/metrics/fill paths.

## Global Constraints

- Spec: [`2026-10-08-spec-e-fill-hard-freeze-design.md`](../specs/2026-10-08-spec-e-fill-hard-freeze-design.md) (all CR + final-nit patches)
- `session_asof` ≠ `--end`; default `latest_trade_day()`; optional `--asof`
- board_calc only when `costs.limit_rule == board_calc_v1` and `D < session_asof` and both `limit_*` empty
- Never overwrite non-empty vendor/`em_*` limits; `limit_source=board_calc_v1`
- Basis = prior **trade calendar** day `close_raw`; optional write-back `preclose_raw`
- `ROUND_HALF_UP` to 0.01; ST 5% before `300`/`301`/`688` 20% else 10%
- `hard_freeze_flag` SoT on bars; N from `a_share_daily.yaml`; metrics **read column only**
- N change ⇒ bump `param_version` + full freeze rewrite before claiming new version (protocol B)
- Passes run after OHLC/flags loop even if `sync_complete=false`; do not flip complete on pass success/fail
- `--time-budget-min` only covers network OHLC/flags loop
- ensure-column + update `BARS_SCHEMA` CREATE; Actions restores existing `bars.db`
- Out of slice: tree-out warmup, asof board_calc, paid limits, EM tfp history, §2.7 tags, temperature/RS changes
- Do not commit dirty `data/cache/trade_dates.json` in feat commits

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/bars.py` | `hard_freeze_flag` in CREATE; `ensure_bars_columns`; `LIMIT_SOURCE_BOARD_CALC` |
| `scripts/common/hard_freeze.py` | streak helper; `apply_hard_freeze_flags` full-U rewrite |
| `scripts/common/board_calc.py` | pct / HALF_UP / `apply_board_calc` |
| `scripts/sync_bars_sample.py` | `--asof`; call ensure + both passes after loop |
| `scripts/eval/costs.py` | `limit_up_unfillable` on `EvalCosts` |
| `scripts/eval/live_shadow_step.py` / `paper_book.py` | pass `limit_up_unfillable=costs.limit_up_unfillable` |
| `scripts/metrics/pipeline.py` | `hard_frozen = is_st ∨ hard_freeze_flag` |
| `scripts/daily_run.py` | `_BARS_SELECT` includes `hard_freeze_flag` |
| `config/eval/costs.yaml` | `board_calc_v1`, `limit_up_unfillable: false`, bump `cost_version` |
| `config/metrics/a_share_daily.yaml` | `hard_freeze_min_suspend_days: 20`, bump `param_version` |
| `tests/test_hard_freeze.py` | streak / migrate / N rewrite / incomplete sync |
| `tests/test_board_calc.py` | hist/asof/vendor/gate/pct/HALF_UP/`session_asof`≠end |
| `tests/test_fill_day.py` / `test_eval_costs_book.py` / pinned `p05-v2` tests | version bumps |
| docs: market-data / metrics §5.5 / backtest-eval / `todo.md` / Spec E status | Done-when |

```text
Task 0 (config bumps + costs loader + pin updates)
  └─► Task 1 (bars ensure-column + CREATE)
        ├─► Task 2 (hard_freeze pass) ──┐
        └─► Task 3 (board_calc pass) ───┴─► Task 4 (sync wire)
                                              └─► Task 5 (metrics + daily_run)
                                                    └─► Task 6 (fill wire from costs)
                                                          └─► Task 7 (docs done-when)
```

Tasks 2 and 3 may proceed in parallel after Task 1. Task 4 waits for both.

---

### Task 0: Config bumps + `limit_up_unfillable` on `EvalCosts`

**Files:**
- Modify: `config/eval/costs.yaml`
- Modify: `config/metrics/a_share_daily.yaml`
- Modify: `scripts/eval/costs.py`
- Modify: `tests/test_fill_day.py`, `tests/test_eval_costs_book.py`, `tests/test_features.py`, `tests/test_daily_run_metrics_wire.py` (and any other `p05-v2` / `cost_version == "v1"` pins revealed by pytest)

**Interfaces:**
- Produces: `EvalCosts.limit_up_unfillable: bool`; `cost_version: v2`; `param_version: p05-v3`; yaml key `hard_freeze_min_suspend_days: 20`

- [ ] **Step 1: Update YAML**

`config/eval/costs.yaml`:

```yaml
cost_version: v2
commission_rate: 0.0003
min_commission: 0
stamp_tax_sell: 0.0005
impact_bp_buy: 5
impact_bp_sell: 5
lot_size: 100
N_cap: 20
initial_cash: 1000000
limit_rule: board_calc_v1
limit_up_unfillable: false
fill_price: open_raw
hs300_series: 000300.SH
```

`config/metrics/a_share_daily.yaml` — change first line and add after `param_version`:

```yaml
param_version: p05-v3
hard_freeze_min_suspend_days: 20
```

(keep all other keys unchanged)

- [ ] **Step 2: Failing test for loader field**

In `tests/test_fill_day.py`, replace `test_load_costs_v1` with:

```python
def test_load_costs_v2_spec_e():
    c = load_costs()
    assert c.cost_version == "v2"
    assert c.limit_rule == "board_calc_v1"
    assert c.limit_up_unfillable is False
    assert c.N_cap == 20
    assert c.fill_price == "open_raw"
```

In `tests/test_eval_costs_book.py`, assert `cost_version == "v2"`.

Add `tests/test_hard_freeze_config.py`:

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / "config" / "metrics" / "a_share_daily.yaml"


def test_hard_freeze_n_and_param_version():
    raw = yaml.safe_load(YAML.read_text(encoding="utf-8"))
    assert raw["param_version"] == "p05-v3"
    assert int(raw["hard_freeze_min_suspend_days"]) == 20
```

- [ ] **Step 3: Run tests — expect FAIL on missing dataclass field / old pins**

Run: `.venv/bin/pytest tests/test_fill_day.py::test_load_costs_v2_spec_e tests/test_hard_freeze_config.py -q`  
Expected: FAIL (`limit_up_unfillable` missing or AttributeError)

- [ ] **Step 4: Implement `EvalCosts` field**

In `scripts/eval/costs.py`:

```python
@dataclass(frozen=True)
class EvalCosts:
    # ...existing fields...
    limit_rule: str
    limit_up_unfillable: bool
    fill_price: str
    hs300_series: str


def load_costs(path: Optional[str | Path] = None) -> EvalCosts:
    p = Path(path) if path else _DEFAULT
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return EvalCosts(
        # ...existing...
        limit_rule=str(data.get("limit_rule") or "vendor_fields"),
        limit_up_unfillable=bool(data.get("limit_up_unfillable", False)),
        fill_price=str(data.get("fill_price") or "open_raw"),
        hs300_series=str(data.get("hs300_series") or "000300.SH"),
    )
```

- [ ] **Step 5: Update `p05-v2` pins to `p05-v3`**

```bash
rg -n "p05-v2" tests --glob '*.py'
```

Replace assertions/fixtures that expect production `param_version == "p05-v2"` with `p05-v3` where they load real `a_share_daily.yaml`. Leave synthetic fixture strings that hardcode their own version alone.

- [ ] **Step 6: Pytest**

Run: `.venv/bin/pytest tests/test_fill_day.py::test_load_costs_v2_spec_e tests/test_eval_costs_book.py tests/test_hard_freeze_config.py tests/test_features.py::test_params_load -q`  
(adjust test name if `test_features` pin differs)  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add config/eval/costs.yaml config/metrics/a_share_daily.yaml scripts/eval/costs.py \
  tests/test_fill_day.py tests/test_eval_costs_book.py tests/test_hard_freeze_config.py \
  tests/test_features.py tests/test_daily_run_metrics_wire.py
# add any other pin files touched
git commit -m "$(cat <<'EOF'
feat(config): Spec E cost_version v2 + param_version p05-v3

EOF
)"
```

---

### Task 1: bars `hard_freeze_flag` schema + ensure-column

**Files:**
- Modify: `scripts/common/bars.py`
- Test: `tests/test_bars_hard_freeze_schema.py`

**Interfaces:**
- Produces: `ensure_bars_columns(conn) -> None`; column `hard_freeze_flag INTEGER NOT NULL DEFAULT 0`; `LIMIT_SOURCE_BOARD_CALC = "board_calc_v1"`

- [ ] **Step 1: Failing migrate test**

```python
# tests/test_bars_hard_freeze_schema.py
import sqlite3
from scripts.common.bars import BARS_SCHEMA, bars_conn, ensure_bars_columns


def test_ensure_adds_hard_freeze_flag(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE bars (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          is_suspended INTEGER NOT NULL DEFAULT 0,
          is_st INTEGER NOT NULL DEFAULT 0,
          flag_source TEXT,
          PRIMARY KEY (ts_code, trade_date)
        );
        """
    )
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    assert "hard_freeze_flag" not in cols
    ensure_bars_columns(conn)
    cols2 = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    assert "hard_freeze_flag" in cols2
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date) VALUES ('000001.SZ','2024-01-08')"
    )
    conn.commit()
    v = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code='000001.SZ'"
    ).fetchone()[0]
    assert int(v) == 0
    conn.close()


def test_bars_conn_create_includes_column(tmp_path, monkeypatch):
    db = tmp_path / "new.db"
    monkeypatch.setattr("scripts.common.bars.DEFAULT_BARS_DB", str(db))
    conn = bars_conn(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    assert "hard_freeze_flag" in cols
    assert "hard_freeze_flag INTEGER" in BARS_SCHEMA.replace("\n", " ") or (
        "hard_freeze_flag" in BARS_SCHEMA
    )
    conn.close()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_bars_hard_freeze_schema.py -q`  
Expected: FAIL (`ensure_bars_columns` missing)

- [ ] **Step 3: Implement**

In `scripts/common/bars.py`:

1. Add to `BARS_SCHEMA` CREATE (after `is_st`):

```text
  hard_freeze_flag INTEGER NOT NULL DEFAULT 0,
```

2. Add constant:

```python
LIMIT_SOURCE_BOARD_CALC = "board_calc_v1"
```

3. Add:

```python
_BARS_ALTER_COLUMNS = (
    ("hard_freeze_flag", "INTEGER NOT NULL DEFAULT 0"),
)


def ensure_bars_columns(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER for columns missing on restored bars.db caches."""
    rows = conn.execute("PRAGMA table_info(bars)").fetchall()
    if not rows:
        return
    existing = {r[1] for r in rows}
    for name, decl in _BARS_ALTER_COLUMNS:
        if name in existing:
            continue
        conn.execute("ALTER TABLE bars ADD COLUMN %s %s" % (name, decl))
        existing.add(name)
    conn.commit()
```

4. Call `ensure_bars_columns(conn)` at end of `bars_conn()` after `executescript(BARS_SCHEMA)`.

- [ ] **Step 4: Pytest PASS**

Run: `.venv/bin/pytest tests/test_bars_hard_freeze_schema.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/common/bars.py tests/test_bars_hard_freeze_schema.py
git commit -m "$(cat <<'EOF'
feat(bars): ensure hard_freeze_flag column on connect

EOF
)"
```

---

### Task 2: `hard_freeze` streak + full-universe apply

**Files:**
- Create: `scripts/common/hard_freeze.py`
- Test: `tests/test_hard_freeze.py`
- Optional tiny helper: `load_hard_freeze_min_suspend_days(path) -> int` in same module

**Interfaces:**
- Consumes: `ensure_bars_columns`; bars rows with `is_suspended`, `flag_source`
- Produces:
  - `load_hard_freeze_min_suspend_days(path: Path | None = None) -> int`
  - `streak_flags(rows: list[tuple[str, int, str | None]], n: int) -> list[int]`
    - `rows` ordered by `trade_date` asc: `(trade_date, is_suspended, flag_source)`
    - only counts when `is_suspended==1` and `flag_source` truthy; gap/`flag_source` empty breaks streak
  - `apply_hard_freeze_flags(conn, ts_codes: Sequence[str], *, n: int, commit: bool = True) -> int`  
    returns rows updated (or symbols processed — pick **rows written** and document in docstring)

- [ ] **Step 1: Failing unit tests**

```python
# tests/test_hard_freeze.py
from scripts.common.hard_freeze import streak_flags, apply_hard_freeze_flags, load_hard_freeze_min_suspend_days
from scripts.common.bars import bars_conn, ensure_bars_columns


def test_load_n_default():
    assert load_hard_freeze_min_suspend_days() == 20


def test_streak_boundary_n():
    # 19 suspended → 0; 20th → 1
    rows = []
    for i in range(1, 21):
        rows.append((f"2024-01-{i:02d}", 1, "baostock"))
    # use flat list of 20 days — only last should be 1 when n=20
    flags = streak_flags(rows, n=20)
    assert flags[:19] == [0] * 19
    assert flags[19] == 1


def test_streak_hole_breaks():
    rows = [
        ("2024-01-02", 1, "baostock"),
        ("2024-01-03", 1, "baostock"),
        # hole: missing 01-04
        ("2024-01-05", 1, "baostock"),
    ]
    # n=3: no day reaches 3
    assert streak_flags(rows, n=3) == [0, 0, 0]


def test_missing_flag_source_breaks():
    rows = [
        ("2024-01-02", 1, "baostock"),
        ("2024-01-03", 1, None),
        ("2024-01-04", 1, "baostock"),
    ]
    assert streak_flags(rows, n=2) == [0, 0, 0]


def test_resume_clears(tmp_path):
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for i, (td, sus) in enumerate([
        ("2024-01-02", 1), ("2024-01-03", 1), ("2024-01-04", 1),
        ("2024-01-05", 0),
    ]):
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,?,?,0)",
            (code, td, sus, "baostock"),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=3)
    got = dict(conn.execute(
        "SELECT trade_date, hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
        (code,),
    ))
    assert got["2024-01-04"] == 1
    assert got["2024-01-05"] == 0


def test_n_change_requires_rewrite(tmp_path):
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "000002.SZ"
    for i in range(1, 26):
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, f"2024-02-{i:02d}"),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=20)
    asof = "2024-02-25"
    assert conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, asof),
    ).fetchone()[0] == 1
    # bump N without rewrite → stale 1 (simulate by not calling apply)
    stale = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, asof),
    ).fetchone()[0]
    assert stale == 1
    apply_hard_freeze_flags(conn, [code], n=60)
    assert conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, asof),
    ).fetchone()[0] == 0
```

Fix February day count in the loop if needed (use 25 consecutive ISO dates via a list). Prefer building dates with `datetime` to avoid invalid calendar days.

- [ ] **Step 2: Run — FAIL**

Run: `.venv/bin/pytest tests/test_hard_freeze.py -q`  
Expected: FAIL import

- [ ] **Step 3: Implement `scripts/common/hard_freeze.py`**

```python
"""Spec E: consecutive is_suspended → bars.hard_freeze_flag."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_METRICS = _ROOT / "config" / "metrics" / "a_share_daily.yaml"


def load_hard_freeze_min_suspend_days(path: Optional[Path] = None) -> int:
    p = Path(path) if path else _DEFAULT_METRICS
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return int(raw.get("hard_freeze_min_suspend_days") or 20)


def streak_flags(
    rows: Sequence[Tuple[str, int, Optional[str]]], n: int
) -> List[int]:
    """rows: (trade_date, is_suspended, flag_source) ascending by trade_date.

    Calendar holes are the caller's responsibility (omit missing days).
    A day without flag_source does not count and resets streak.
    """
    out: List[int] = []
    streak = 0
    prev_td: Optional[str] = None
    for td, sus, src in rows:
        # If caller includes only existing rows, "hole" = non-consecutive calendar
        # is NOT detected here — apply_* must only feed contiguous trade-calendar
        # rows OR reset when prev trade-calendar day missing.
        if not src:
            streak = 0
            out.append(0)
            prev_td = td
            continue
        if int(sus) == 1:
            streak += 1
        else:
            streak = 0
        out.append(1 if streak >= int(n) else 0)
        prev_td = td
    return out
```

**Important:** In `apply_hard_freeze_flags`, load each symbol's rows ordered by `trade_date`, and **reset streak when `prev_trade_date(td) != previous row's date`** (use `scripts.common.calendar.prev_trade_date`). That implements "空洞不计 / 不跨洞虚增".

```python
def apply_hard_freeze_flags(
    conn,
    ts_codes: Sequence[str],
    *,
    n: int,
    commit: bool = True,
) -> int:
    from datetime import date
    from scripts.common.calendar import prev_trade_date

    written = 0
    for ts in ts_codes:
        rows = conn.execute(
            """
            SELECT trade_date, is_suspended, flag_source
            FROM bars WHERE ts_code=? ORDER BY trade_date ASC
            """,
            (ts,),
        ).fetchall()
        streak = 0
        prev_td = None
        for td_s, sus, src in rows:
            td = date.fromisoformat(str(td_s)[:10])
            if prev_td is not None:
                expect = prev_trade_date(td)
                if expect is None or expect != prev_td:
                    streak = 0
            if not src:
                streak = 0
                flag = 0
            elif int(sus or 0) == 1:
                streak += 1
                flag = 1 if streak >= n else 0
            else:
                streak = 0
                flag = 0
            conn.execute(
                "UPDATE bars SET hard_freeze_flag=? WHERE ts_code=? AND trade_date=?",
                (flag, ts, td_s),
            )
            written += 1
            prev_td = td
    if commit:
        conn.commit()
    return written
```

Keep `streak_flags` for pure unit tests; either duplicate hole logic there with explicit missing days, or unit-test holes only via `apply_*` + calendar monkeypatch (`load_trade_dates_from_list`).

- [ ] **Step 4: Pytest PASS**

Run: `.venv/bin/pytest tests/test_hard_freeze.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/common/hard_freeze.py tests/test_hard_freeze.py
git commit -m "$(cat <<'EOF'
feat(hard_freeze): streak≥N writes bars.hard_freeze_flag

EOF
)"
```

---

### Task 3: `board_calc_v1` apply pass

**Files:**
- Create: `scripts/common/board_calc.py`
- Test: `tests/test_board_calc.py`

**Interfaces:**
- Consumes: `LIMIT_SOURCE_BOARD_CALC`, `prev_trade_date`, `EvalCosts.limit_rule` / path load
- Produces:
  - `board_pct(ts_code: str, is_st: int) -> float`
  - `limit_prices(preclose: float, pct: float) -> tuple[float, float]`  # HALF_UP
  - `apply_board_calc(conn, ts_codes, *, session_asof: date, limit_rule: str, commit: bool = True) -> int`

- [ ] **Step 1: Failing tests**

```python
# tests/test_board_calc.py
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from scripts.common.bars import bars_conn, LIMIT_SOURCE_BOARD_CALC, LIMIT_SOURCE_EM
from scripts.common.board_calc import board_pct, limit_prices, apply_board_calc
from scripts.common.calendar import load_trade_dates_from_list


def test_board_pct_st_priority_and_prefixes():
    assert board_pct("300001.SZ", 1) == 0.05
    assert board_pct("301001.SZ", 0) == 0.20
    assert board_pct("688001.SH", 0) == 0.20
    assert board_pct("600000.SH", 0) == 0.10


def test_half_up_not_bankers():
    # 1.15 * 1.1 = 1.265 → HALF_UP 1.27; Python round → 1.26
    up, down = limit_prices(1.15, 0.10)
    assert up == 1.27
    assert round(1.15 * 1.1, 2) == 1.26  # document divergence


def test_hist_fill_and_asof_skip(tmp_path):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, is_st, flag_source)"
        " VALUES (?,?,?,?, 'baostock')",
        (code, "2024-01-05", 10.0, 0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, is_st, flag_source)"
        " VALUES (?,?,?,?, 'baostock')",
        (code, "2024-01-08", 10.5, 0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, is_st, flag_source)"
        " VALUES (?,?,?,?, 'baostock')",
        (code, "2024-01-09", 10.6, 0),
    )
    conn.commit()
    asof = date(2024, 1, 9)
    n = apply_board_calc(conn, [code], session_asof=asof, limit_rule="board_calc_v1")
    assert n >= 1
    hist = conn.execute(
        "SELECT limit_up, limit_down, limit_source, preclose_raw FROM bars"
        " WHERE ts_code=? AND trade_date='2024-01-08'",
        (code,),
    ).fetchone()
    assert hist[2] == LIMIT_SOURCE_BOARD_CALC
    assert hist[3] == 10.0
    assert hist[0] == 11.0 and hist[1] == 9.0
    asof_row = conn.execute(
        "SELECT limit_up, limit_source FROM bars WHERE ts_code=? AND trade_date='2024-01-09'",
        (code,),
    ).fetchone()
    assert asof_row[0] is None and asof_row[1] is None


def test_no_overwrite_vendor(tmp_path):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
        (code, "2024-01-05", 10.0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw, limit_up, limit_down, limit_source)"
        " VALUES (?,?,?,?,?,?)",
        (code, "2024-01-08", 10.5, 12.0, 8.0, LIMIT_SOURCE_EM),
    )
    conn.commit()
    apply_board_calc(
        conn, [code], session_asof=date(2024, 1, 9), limit_rule="board_calc_v1"
    )
    up, src = conn.execute(
        "SELECT limit_up, limit_source FROM bars WHERE trade_date='2024-01-08'"
    ).fetchone()
    assert up == 12.0 and src == LIMIT_SOURCE_EM


def test_limit_rule_gate(tmp_path):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
        (code, "2024-01-05", 10.0),
    )
    conn.execute(
        "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
        (code, "2024-01-08", 10.5),
    )
    conn.commit()
    apply_board_calc(
        conn, [code], session_asof=date(2024, 1, 9), limit_rule="vendor_fields"
    )
    assert conn.execute(
        "SELECT limit_up FROM bars WHERE trade_date='2024-01-08'"
    ).fetchone()[0] is None


def test_session_asof_not_end(tmp_path):
    """--end historical day must still board_calc when session_asof is newer."""
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    conn = bars_conn(str(tmp_path / "b.db"))
    code = "600000.SH"
    for td, px in [("2024-01-05", 10.0), ("2024-01-08", 10.5)]:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, close_raw) VALUES (?,?,?)",
            (code, td, px),
        )
    conn.commit()
    apply_board_calc(
        conn, [code], session_asof=date(2024, 1, 9), limit_rule="board_calc_v1"
    )
    assert conn.execute(
        "SELECT limit_source FROM bars WHERE trade_date='2024-01-08'"
    ).fetchone()[0] == LIMIT_SOURCE_BOARD_CALC
```

- [ ] **Step 2: Run — FAIL**

Run: `.venv/bin/pytest tests/test_board_calc.py -q`  
Expected: FAIL import

- [ ] **Step 3: Implement `scripts/common/board_calc.py`**

```python
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional, Sequence, Tuple

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
    asof_s = session_asof.isoformat()
    n_write = 0
    for ts in ts_codes:
        rows = conn.execute(
            """
            SELECT trade_date, close_raw, is_st, limit_up, limit_down
            FROM bars WHERE ts_code=? ORDER BY trade_date ASC
            """,
            (to_ts_code(ts),),
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
            pct = board_pct(ts, int(is_st or 0))
            lu, ld = limit_prices(basis_f, pct)
            conn.execute(
                """
                UPDATE bars
                SET limit_up=?, limit_down=?, limit_source=?, preclose_raw=?
                WHERE ts_code=? AND trade_date=?
                  AND limit_up IS NULL AND limit_down IS NULL
                """,
                (lu, ld, LIMIT_SOURCE_BOARD_CALC, basis_f, to_ts_code(ts), td_s),
            )
            if conn.total_changes:  # careful: better use cursor.rowcount
                n_write += 1
    if commit:
        conn.commit()
    return n_write
```

Use `cur = conn.execute(...); n_write += cur.rowcount` instead of `total_changes`.

- [ ] **Step 4: Pytest PASS**

Run: `.venv/bin/pytest tests/test_board_calc.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/common/board_calc.py tests/test_board_calc.py
git commit -m "$(cat <<'EOF'
feat(board_calc): hist-only limit fill with board_calc_v1 source

EOF
)"
```

---

### Task 4: Wire passes into `sync_bars_sample.py`

**Files:**
- Modify: `scripts/sync_bars_sample.py`
- Test: `tests/test_sync_spec_e_passes.py`

**Interfaces:**
- Consumes: `ensure_bars_columns`, `apply_hard_freeze_flags`, `load_hard_freeze_min_suspend_days`, `apply_board_calc`, `load_costs`
- Produces: CLI `--asof`; after OHLC/flags (+ limits), always run both passes; `session_asof` from `--asof` or `latest_trade_day()`

- [ ] **Step 1: Failing integration test**

```python
# tests/test_sync_spec_e_passes.py
import datetime as dt
from scripts.common.bars import bars_conn
from scripts.common.calendar import load_trade_dates_from_list
import scripts.sync_bars_sample as sync_mod


def test_passes_run_when_complete_false(tmp_path, monkeypatch):
    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    code = "600000.SH"
    for i in range(20):
        # build 20 suspended days ending 2024-01-08 via helper dates list
        pass  # implement with explicit date list of length 20 + clear day
    # ... insert flags + prior close for board_calc ...
    conn.close()

    calls = {"freeze": 0, "board": 0}

    def fake_freeze(conn, codes, *, n, commit=True):
        calls["freeze"] += 1
        return 0

    def fake_board(conn, codes, *, session_asof, limit_rule, commit=True):
        calls["board"] += 1
        return 0

    monkeypatch.setattr(sync_mod, "apply_hard_freeze_flags", fake_freeze)
    monkeypatch.setattr(sync_mod, "apply_board_calc", fake_board)
    monkeypatch.setattr(sync_mod, "bars_conn", lambda: bars_conn(str(db)))
    monkeypatch.setattr(sync_mod, "codes_from_universe", lambda *a, **k: [code])
    monkeypatch.setattr(sync_mod, "sync_symbol_bars", lambda *a, **k: 0)
    monkeypatch.setattr(sync_mod, "sync_baostock_flags", lambda *a, **k: 0)
    # force budget hit immediately
    monkeypatch.setattr(
        sync_mod.dt, "datetime",
        type("X", (), {
            "utcnow": staticmethod(lambda: dt.datetime(2024, 1, 1)),
            "strptime": dt.datetime.strptime,
        }),
    )
    # Simpler: pass --time-budget-min 0.0001 and make first code need work —
    # OR call an extracted run_post_sync_passes(conn, codes, session_asof) unit.

```

**Prefer extract** for testability:

```python
# in sync_bars_sample.py
def run_spec_e_passes(conn, codes, *, session_asof: dt.date) -> None:
    from scripts.common.hard_freeze import (
        apply_hard_freeze_flags,
        load_hard_freeze_min_suspend_days,
    )
    from scripts.common.board_calc import apply_board_calc
    from scripts.eval.costs import load_costs
    from scripts.common.bars import ensure_bars_columns

    ensure_bars_columns(conn)
    try:
        n = load_hard_freeze_min_suspend_days()
        apply_hard_freeze_flags(conn, codes, n=n)
    except Exception as e:
        print("[sync_bars] warn: hard_freeze skipped: %s" % e, file=sys.stderr)
    try:
        costs = load_costs()
        apply_board_calc(
            conn, codes, session_asof=session_asof, limit_rule=costs.limit_rule
        )
    except Exception as e:
        print("[sync_bars] warn: board_calc skipped: %s" % e, file=sys.stderr)
```

Test:

```python
def test_run_spec_e_passes_invokes_both(tmp_path, monkeypatch):
    conn = bars_conn(str(tmp_path / "b.db"))
    seen = []
    monkeypatch.setattr(
        "scripts.sync_bars_sample.apply_hard_freeze_flags",
        lambda *a, **k: seen.append("f") or 0,
    )
    # import inside function — patch hard_freeze/board_calc modules instead
```

Patch `scripts.common.hard_freeze.apply_hard_freeze_flags` and `scripts.common.board_calc.apply_board_calc` before calling `run_spec_e_passes`.

Also:

```python
def test_incomplete_still_calls_passes(monkeypatch, tmp_path):
    # main() with time budget forcing complete=False still calls run_spec_e_passes once
    ...
```

- [ ] **Step 2: Implement CLI + call site**

In `main()`:

```python
p.add_argument("--asof", default="", help="session_asof YYYY-MM-DD (default: latest_trade_day)")
# after parsing:
session_asof = (
    dt.datetime.strptime(args.asof, "%Y-%m-%d").date()
    if args.asof
    else latest_trade_day()
)
# after OHLC/flags loop and with_limits block, BEFORE write_sync_complete:
try:
    run_spec_e_passes(conn, codes, session_asof=session_asof)
except Exception as e:
    print("[sync_bars] warn: spec_e passes: %s" % e, file=sys.stderr)
# do not modify `complete` here
write_sync_complete(complete, elapsed_min)
```

- [ ] **Step 3: Pytest PASS**

Run: `.venv/bin/pytest tests/test_sync_spec_e_passes.py -q`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/sync_bars_sample.py tests/test_sync_spec_e_passes.py
git commit -m "$(cat <<'EOF'
feat(sync): run hard_freeze + board_calc passes after bar sync

EOF
)"
```

---

### Task 5: metrics + `daily_run` read `hard_freeze_flag`

**Files:**
- Modify: `scripts/metrics/pipeline.py` (`replay_from_ohlc` hard line)
- Modify: `scripts/daily_run.py` (`_BARS_SELECT` + `_load_symbol_bars`)
- Test: `tests/test_pipeline_hard_freeze_flag.py` (new) and/or extend `tests/test_fsm.py` / `tests/test_daily_run_metrics_wire.py`

**Interfaces:**
- Consumes: bar dict field `hard_freeze_flag`
- Produces: `hard_frozen = bool(is_st) or bool(hard_freeze_flag)`

- [ ] **Step 1: Failing test**

```python
# tests/test_pipeline_hard_freeze_flag.py
from scripts.metrics.params import load_params
from scripts.metrics.pipeline import replay_from_ohlc


def _rec(td, close, is_st=0, hard_freeze_flag=0):
    return {
        "trade_date": td,
        "close_qfq": close,
        "high_qfq": close,
        "low_qfq": close,
        "is_st": is_st,
        "is_suspended": 0,
        "hard_freeze_flag": hard_freeze_flag,
    }


def test_hard_freeze_flag_ors_into_hard_frozen():
    params = load_params()
    # Need enough history for features — reuse pattern from existing pipeline tests
    # Minimal: monkeypatch decide/features OR build 300-day series ending with flag=1
    ...
```

Faster path — unit the assignment line via a tiny pure helper if you extract:

```python
# scripts/metrics/pipeline.py
def bar_hard_frozen(bar) -> bool:
    return bool(int(bar.get("is_st") or 0)) or bool(int(bar.get("hard_freeze_flag") or 0))
```

```python
def test_bar_hard_frozen_or():
    from scripts.metrics.pipeline import bar_hard_frozen
    assert bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 1}) is True
    assert bar_hard_frozen({"is_st": 1, "hard_freeze_flag": 0}) is True
    assert bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 0}) is False
```

Plus FSM integration already covered by `test_hard_frozen_*` when `hard_frozen=True` is passed — add one `replay_from_ohlc` test with flag set on last day if cheap.

`daily_run` load test:

```python
def test_load_symbol_bars_includes_flag(tmp_path, monkeypatch):
    # insert bar with hard_freeze_flag=1, call _load_symbol_bars, assert key present
```

- [ ] **Step 2: Implement**

`pipeline.py`:

```python
hard = bool(int(bar.get("is_st") or 0)) or bool(int(bar.get("hard_freeze_flag") or 0))
```

Update docstring that currently says ``hard_frozen`` is ``bool(is_st)`` only.

`daily_run.py`:

```python
_BARS_SELECT = """
SELECT trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
       is_st, is_suspended, float_mv, amount, hard_freeze_flag
FROM bars
WHERE ts_code=? AND trade_date<=?
ORDER BY trade_date ASC
"""
# in _load_symbol_bars:
"hard_freeze_flag": r[9],
```

- [ ] **Step 3: Pytest**

Run: `.venv/bin/pytest tests/test_pipeline_hard_freeze_flag.py tests/test_fsm.py -q`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/metrics/pipeline.py scripts/daily_run.py tests/test_pipeline_hard_freeze_flag.py
git commit -m "$(cat <<'EOF'
feat(metrics): OR hard_freeze_flag into hard_frozen

EOF
)"
```

---

### Task 6: Pass `limit_up_unfillable` from costs into fill callers

**Files:**
- Modify: `scripts/eval/live_shadow_step.py`
- Modify: `scripts/eval/paper_book.py` (every `fill_day(...)` call)
- Test: extend `tests/test_fill_day.py` — assert default false keeps sell-on-limit-up attempt; optional true defers

**Interfaces:**
- Consumes: `EvalCosts.limit_up_unfillable`
- Produces: `fill_day(..., limit_up_unfillable=costs.limit_up_unfillable)`

- [ ] **Step 1: Grep callers**

```bash
rg -n "fill_day\(" scripts/eval tests --glob '*.py'
```

- [ ] **Step 2: Wire**

```python
fills = fill_day(
    ...,
    costs,
    limit_up_unfillable=costs.limit_up_unfillable,
)
```

- [ ] **Step 3: Test sell still fills at limit-up when false** (existing behavior)

```python
def test_limit_up_sell_still_fills_when_unfillable_false():
    # open_raw >= limit_up, limit_up_unfillable=False → filled sell
    ...
```

- [ ] **Step 4: Pytest + commit**

```bash
git add scripts/eval/live_shadow_step.py scripts/eval/paper_book.py tests/test_fill_day.py
git commit -m "$(cat <<'EOF'
feat(fill): thread limit_up_unfillable from costs.yaml

EOF
)"
```

---

### Task 7: Docs done-when

**Files:**
- Modify: `docs/superpowers/specs/2026-10-01-market-data-contract-design.md` §5.2 + bars column
- Modify: `docs/superpowers/specs/2026-09-29-trend-metrics-engine-design.md` §5.5 (N landed; column synonym)
- Modify: `docs/superpowers/specs/2026-09-30-backtest-eval-design.md` §4.2–4.3
- Modify: `docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md` status → 已落地 + plan link
- Modify: `todo.md` §2.5–2.6 / Spec E row → 已完成

- [ ] **Step 1: Edit market-data §5.2** — mark `board_calc_v1` enabled path; hist-only; prior `close_raw` basis; `hard_freeze_flag` formal; N knob name

- [ ] **Step 2: Edit metrics §5.5** — replace “MVP 不另定连续 N 日” with Spec E N=20 + persist column; note protocol B for N changes

- [ ] **Step 3: Edit backtest-eval** — hist may carry `board_calc_v1` limits; costs example `v2` / `limit_up_unfillable: false`

- [ ] **Step 4: Spec E + todo**

Spec header:

```markdown
**状态：** 已落地；plan [`2026-10-08-spec-e-fill-hard-freeze.md`](../plans/2026-10-08-spec-e-fill-hard-freeze.md)
```

`todo.md`: Spec E row **已完成**; §2.5–2.6 strike/complete like Spec D.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-10-01-market-data-contract-design.md \
  docs/superpowers/specs/2026-09-29-trend-metrics-engine-design.md \
  docs/superpowers/specs/2026-09-30-backtest-eval-design.md \
  docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md \
  todo.md
git commit -m "$(cat <<'EOF'
docs: mark Spec E fill/hard-freeze landed in contracts and todo

EOF
)"
```

---

## Spec coverage checklist (self-review)

| Spec requirement | Task |
|------------------|------|
| hist board_calc + asof ban | 3, 4 |
| `session_asof` ≠ `--end` | 3 test + 4 |
| `limit_rule` gate / no vendor overwrite | 3 |
| prior `close_raw` + HALF_UP + 300/301/688/ST | 3 |
| `limit_up_unfillable` explicit false + loader | 0, 6 |
| `cost_version` / `param_version` bump | 0 |
| `hard_freeze_flag` ensure + CREATE | 1 |
| streak N=20, holes, resume clear | 2 |
| full-U rewrite; N change protocol B fixture | 2 |
| passes after loop; incomplete still runs | 4 |
| metrics OR flag; daily_run SELECT | 5 |
| docs touchpoints | 7 |

No TBD placeholders. Types: `apply_*` return `int` row counts; `session_asof: date`; `limit_rule: str`.

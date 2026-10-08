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
| `config/metrics/a_share_daily.yaml` | Task 0: add `hard_freeze_min_suspend_days: 20` (**keep** `param_version` until Task 5); Task 5: bump → `p05-v3` |
| `tests/test_hard_freeze.py` | streak via `apply_*`+calendar / N rewrite mid-state / resume |
| `tests/test_board_calc.py` | hist/asof/vendor/gate/pct/HALF_UP/`session_asof`≠end |
| `tests/test_sync_spec_e_passes.py` | passes on full mapped U; `session_asof`≠`--end`; incomplete + `complete=False` |
| `tests/test_fill_day.py` / `test_eval_costs_book.py` | `cost_version` v2 + `limit_up_unfillable` |
| `tests/test_features.py` / `test_daily_run_metrics_wire.py` | Task 5: real-yaml `p05-v3` pins |
| `scripts/eval/paper_book.py` / fill summary path | emit `limit_rule` + `cost_version` from payload `costs` |
| docs: market-data / metrics §5.5 / backtest-eval / `todo.md` / Spec E status | Done-when |
| `.github/workflows/daily-trend.yml` | **no change required** — sync default `session_asof=latest_trade_day()` |

```text
Task 0 (costs v2 + N knob; NOT param_version yet)
  └─► Task 1 (bars ensure-column + CREATE)
        ├─► Task 2 (hard_freeze pass) ──┐
        └─► Task 3 (board_calc pass) ───┴─► Task 4 (sync wire: full-U passes, before close)
                                              └─► Task 5 (metrics OR + param_version p05-v3)
                                                    └─► Task 6 (fill + summary limit_rule)
                                                          └─► Task 7 (docs done-when)
```

Tasks 2 and 3 may proceed in parallel after Task 1. Task 4 waits for both.

---

### Task 0: Costs v2 + `hard_freeze_min_suspend_days` (defer `param_version`)

**Files:**
- Modify: `config/eval/costs.yaml`
- Modify: `config/metrics/a_share_daily.yaml` (**add N only** — leave `param_version: p05-v2`)
- Modify: `scripts/eval/costs.py`
- Modify: `tests/test_fill_day.py`, `tests/test_eval_costs_book.py`
- Create: `tests/test_hard_freeze_config.py`

**Interfaces:**
- Produces: `EvalCosts.limit_up_unfillable: bool`; `cost_version: v2`; yaml `hard_freeze_min_suspend_days: 20`
- **Does not** bump `param_version` (protocol B: claim `p05-v3` only in Task 5 after freeze rewrite + metrics OR)

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

`config/metrics/a_share_daily.yaml` — **keep** `param_version: p05-v2`; insert after it:

```yaml
hard_freeze_min_suspend_days: 20
```

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


def test_hard_freeze_n_knob_present():
    raw = yaml.safe_load(YAML.read_text(encoding="utf-8"))
    assert int(raw["hard_freeze_min_suspend_days"]) == 20
    # param_version bump is Task 5 — still p05-v2 here
    assert raw["param_version"] == "p05-v2"
```

- [ ] **Step 3: Run tests — expect FAIL**

Run: `.venv/bin/pytest tests/test_fill_day.py::test_load_costs_v2_spec_e tests/test_hard_freeze_config.py -q`  
Expected: FAIL (`limit_up_unfillable` missing or AttributeError)

- [ ] **Step 4: Implement `EvalCosts` field**

In `scripts/eval/costs.py`, add field after `limit_rule`:

```python
limit_up_unfillable: bool
```

In `load_costs`:

```python
limit_up_unfillable=bool(data.get("limit_up_unfillable", False)),
```

(keep all other `EvalCosts` fields/order as today; insert the new kwarg next to `limit_rule=...`)

- [ ] **Step 5: Pytest**

Run: `.venv/bin/pytest tests/test_fill_day.py::test_load_costs_v2_spec_e tests/test_eval_costs_book.py tests/test_hard_freeze_config.py -q`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/eval/costs.yaml config/metrics/a_share_daily.yaml scripts/eval/costs.py \
  tests/test_fill_day.py tests/test_eval_costs_book.py tests/test_hard_freeze_config.py
git commit -m "$(cat <<'EOF'
feat(config): Spec E cost_version v2 and hard_freeze N knob

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
- Consumes: `ensure_bars_columns`; bars rows with `is_suspended`, `flag_source`; trade calendar via `prev_trade_date`
- Produces:
  - `load_hard_freeze_min_suspend_days(path: Path | None = None) -> int`
  - `apply_hard_freeze_flags(conn, ts_codes: Sequence[str], *, n: int, commit: bool = True) -> int`  
    (**sole** streak implementation — rows written count). Resets streak when `flag_source` empty, `is_suspended!=1`, or `prev_trade_date(td) != previous row date` (calendar hole).

**Do not** ship a separate `streak_flags` helper that ignores the calendar — that caused a contradictory hole test in draft v1.

- [ ] **Step 1: Failing unit tests**

```python
# tests/test_hard_freeze.py
from datetime import date, timedelta

from scripts.common.hard_freeze import apply_hard_freeze_flags, load_hard_freeze_min_suspend_days
from scripts.common.bars import bars_conn, ensure_bars_columns
from scripts.common.calendar import load_trade_dates_from_list


def _consec(start: date, n: int) -> list[str]:
    out = []
    d = start
    for _ in range(n):
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_load_n_default():
    assert load_hard_freeze_min_suspend_days() == 20


def test_streak_boundary_n(tmp_path):
    days = _consec(date(2024, 1, 2), 25)
    load_trade_dates_from_list(days)
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td in days[:20]:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=20)
    flags = [
        r[0]
        for r in conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
            (code,),
        )
    ]
    assert flags[:19] == [0] * 19
    assert flags[19] == 1


def test_streak_hole_breaks(tmp_path):
    # calendar has 01-04 but bar row missing → streak must reset
    load_trade_dates_from_list(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td in ("2024-01-02", "2024-01-03", "2024-01-05"):
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=3)
    got = dict(
        conn.execute(
            "SELECT trade_date, hard_freeze_flag FROM bars WHERE ts_code=?",
            (code,),
        )
    )
    assert got == {"2024-01-02": 0, "2024-01-03": 0, "2024-01-05": 0}


def test_missing_flag_source_breaks(tmp_path):
    load_trade_dates_from_list(["2024-01-02", "2024-01-03", "2024-01-04"])
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    rows = [
        ("2024-01-02", 1, "baostock"),
        ("2024-01-03", 1, None),
        ("2024-01-04", 1, "baostock"),
    ]
    for td, sus, src in rows:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,?,?,0)",
            (code, td, sus, src),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=2)
    flags = [
        r[0]
        for r in conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
            (code,),
        )
    ]
    assert flags == [0, 0, 0]


def test_resume_clears(tmp_path):
    load_trade_dates_from_list(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    )
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000001.SZ"
    for td, sus in [
        ("2024-01-02", 1),
        ("2024-01-03", 1),
        ("2024-01-04", 1),
        ("2024-01-05", 0),
    ]:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,?,?,0)",
            (code, td, sus, "baostock"),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=3)
    got = dict(
        conn.execute(
            "SELECT trade_date, hard_freeze_flag FROM bars WHERE ts_code=? ORDER BY trade_date",
            (code,),
        )
    )
    assert got["2024-01-04"] == 1
    assert got["2024-01-05"] == 0


def test_n_change_requires_rewrite(tmp_path):
    days = _consec(date(2024, 2, 1), 25)
    load_trade_dates_from_list(days)
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_bars_columns(conn)
    code = "000002.SZ"
    for td in days:
        conn.execute(
            "INSERT INTO bars (ts_code, trade_date, is_suspended, flag_source, hard_freeze_flag)"
            " VALUES (?,?,1,'baostock',0)",
            (code, td),
        )
    conn.commit()
    apply_hard_freeze_flags(conn, [code], n=20)
    asof = days[-1]
    assert (
        conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
            (code, asof),
        ).fetchone()[0]
        == 1
    )
    # Spec §5.2#10 mid-state: yaml N conceptually 60 but no rewrite → flag stays old
    stale = conn.execute(
        "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
        (code, asof),
    ).fetchone()[0]
    assert stale == 1
    apply_hard_freeze_flags(conn, [code], n=60)
    assert (
        conn.execute(
            "SELECT hard_freeze_flag FROM bars WHERE ts_code=? AND trade_date=?",
            (code, asof),
        ).fetchone()[0]
        == 0
    )
```

Note: `_consec` uses calendar days for a compact fixture; pair with `load_trade_dates_from_list` so `prev_trade_date` matches the inserted spine (weekend-free list).

- [ ] **Step 2: Run — FAIL**

Run: `.venv/bin/pytest tests/test_hard_freeze.py -q`  
Expected: FAIL import

- [ ] **Step 3: Implement `scripts/common/hard_freeze.py`**

```python
"""Spec E: consecutive is_suspended → bars.hard_freeze_flag."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Sequence

import yaml

from scripts.common.calendar import prev_trade_date

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_METRICS = _ROOT / "config" / "metrics" / "a_share_daily.yaml"


def load_hard_freeze_min_suspend_days(path: Optional[Path] = None) -> int:
    p = Path(path) if path else _DEFAULT_METRICS
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return int(raw.get("hard_freeze_min_suspend_days") or 20)


def apply_hard_freeze_flags(
    conn,
    ts_codes: Sequence[str],
    *,
    n: int,
    commit: bool = True,
) -> int:
    """Rewrite hard_freeze_flag for each ts_code. Returns number of rows touched."""
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
```

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
- Consumes: `ensure_bars_columns`, `apply_hard_freeze_flags`, `load_hard_freeze_min_suspend_days`, `apply_board_calc`, `load_costs`, `codes_from_universe`
- Produces: CLI `--asof`; `session_asof` from `--asof` or `latest_trade_day()` (**never** `--end`); passes always scan **full mapped U** via `codes_from_universe()` (OHLC loop may still honor `--codes`); call **after** `with_limits` block and **before** `conn.close()`

- [ ] **Step 1: Extract helper**

```python
def run_spec_e_passes(conn, codes, *, session_asof: dt.date) -> None:
    from scripts.common.bars import ensure_bars_columns
    from scripts.common.board_calc import apply_board_calc
    from scripts.common.hard_freeze import (
        apply_hard_freeze_flags,
        load_hard_freeze_min_suspend_days,
    )
    from scripts.eval.costs import load_costs

    ensure_bars_columns(conn)
    try:
        n = load_hard_freeze_min_suspend_days()
        apply_hard_freeze_flags(conn, codes, n=n)
    except Exception as e:  # noqa: BLE001
        print("[sync_bars] warn: hard_freeze skipped: %s" % e, file=sys.stderr)
    try:
        costs = load_costs()
        apply_board_calc(
            conn, codes, session_asof=session_asof, limit_rule=costs.limit_rule
        )
    except Exception as e:  # noqa: BLE001
        print("[sync_bars] warn: board_calc skipped: %s" % e, file=sys.stderr)
```

- [ ] **Step 2: Failing tests (no escape hatches)**

```python
# tests/test_sync_spec_e_passes.py
import datetime as dt

from scripts.common.bars import bars_conn
from scripts.sync_bars_sample import main, run_spec_e_passes


def test_run_spec_e_passes_invokes_both(tmp_path, monkeypatch):
    conn = bars_conn(str(tmp_path / "b.db"))
    seen: list[str] = []
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: seen.append("freeze") or 0,
    )
    monkeypatch.setattr(
        "scripts.common.board_calc.apply_board_calc",
        lambda *a, **k: seen.append("board") or 0,
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.load_hard_freeze_min_suspend_days",
        lambda: 20,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "board_calc_v1"})(),
    )
    run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
    assert seen == ["freeze", "board"]


def test_main_passes_use_full_universe_not_codes_argv(tmp_path, monkeypatch):
    """Spec: passes scan mapped U; --codes only limits OHLC/flags loop."""
    db = tmp_path / "b.db"
    got = {}

    def _passes(conn, codes, *, session_asof):
        got["codes"] = list(codes)
        got["asof"] = session_asof

    monkeypatch.setattr("scripts.sync_bars_sample.run_spec_e_passes", _passes)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["AAA.SZ", "BBB.SZ"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: dt.date(2024, 1, 9),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.write_sync_complete",
        lambda *a, **k: None,
    )
    rc = main(
        ["--end", "2024-01-05", "--asof", "2024-01-09", "--codes", "AAA.SZ"]
    )
    assert rc == 0
    assert got["codes"] == ["AAA.SZ", "BBB.SZ"]
    assert got["asof"] == dt.date(2024, 1, 9)  # not --end


def test_incomplete_still_calls_passes_and_keeps_complete_false(
    tmp_path, monkeypatch
):
    db = tmp_path / "b.db"
    calls = {"n": 0, "complete": None}

    def _passes(conn, codes, *, session_asof):
        calls["n"] += 1

    def _wsc(complete, elapsed_min=0.0):
        calls["complete"] = complete

    # Force budget hit: max-codes=1 with two universe names needing OHLC
    monkeypatch.setattr("scripts.sync_bars_sample.run_spec_e_passes", _passes)
    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn", lambda: bars_conn(str(db))
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH", "600001.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.sync_symbol_bars", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day",
        lambda: dt.date(2024, 1, 9),
    )
    rc = main(
        ["--end", "2024-01-09", "--max-codes", "1", "--skip-flags"]
    )
    assert rc == 0
    assert calls["n"] == 1
    assert calls["complete"] is False
```

- [ ] **Step 3: Wire `main()` call site (exact order)**

Current tail of `main` today:

```python
    if args.with_limits and complete:
        asof = latest_trade_day()
        ...
    conn.close()
    elapsed_min = ...
    write_sync_complete(complete, elapsed_min)
```

Replace with:

```python
    p.add_argument("--asof", default="", help="session_asof (default latest_trade_day)")
    # after parse:
    session_asof = (
        dt.datetime.strptime(args.asof, "%Y-%m-%d").date()
        if args.asof
        else latest_trade_day()
    )
    # OHLC loop still uses `codes` from --codes / --from-universe / universe

    if args.with_limits and complete:
        if end != session_asof:  # was: latest_trade_day()
            print("[sync_bars] skip --with-limits (end=%s != asof %s)" % (end, session_asof))
        else:
            ... sync_em_limits_asof(conn, end, ...) ...

    # Spec E passes: full mapped U, open connection
    pass_codes = codes_from_universe(args.from_universe) if args.from_universe else codes_from_universe()
    run_spec_e_passes(conn, pass_codes, session_asof=session_asof)
    # do not change `complete` here

    conn.close()
    elapsed_min = (dt.datetime.utcnow() - started).total_seconds() / 60.0
    write_sync_complete(complete, elapsed_min)
```

When `--from-universe` is a fixture path, `pass_codes` may equal that fixture’s mapped set (tests). Production cron omits `--codes`/`--from-universe` → full mapped U.

**Actions:** leave `.github/workflows/daily-trend.yml` unchanged.

- [ ] **Step 4: Pytest PASS**

Run: `.venv/bin/pytest tests/test_sync_spec_e_passes.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_bars_sample.py tests/test_sync_spec_e_passes.py
git commit -m "$(cat <<'EOF'
feat(sync): run hard_freeze + board_calc passes after bar sync

EOF
)"
```

---

### Task 5: metrics + `daily_run` read flag + bump `param_version`

**Files:**
- Modify: `scripts/metrics/pipeline.py` (`replay_from_ohlc` hard line)
- Modify: `scripts/daily_run.py` (`_BARS_SELECT` + `_load_symbol_bars`)
- Modify: `config/metrics/a_share_daily.yaml` — `param_version: p05-v3`
- Modify: `tests/test_features.py`, `tests/test_daily_run_metrics_wire.py`, `tests/test_hard_freeze_config.py`
- Test: `tests/test_pipeline_hard_freeze_flag.py`

**Interfaces:**
- Consumes: bar dict field `hard_freeze_flag`
- Produces: `hard_frozen = is_st ∨ hard_freeze_flag`; live yaml `param_version: p05-v3` (protocol B: freeze pass + OR already landed in Tasks 2–4/this task)

- [ ] **Step 1: Failing tests**

```python
# tests/test_pipeline_hard_freeze_flag.py
import datetime as dt

from scripts.common.bars import bars_conn, ensure_bars_columns
from scripts.daily_run import _load_symbol_bars
from scripts.metrics.fsm import (
    EVENT_EXIT,
    EXIT_KIND_UNTRADABLE,
    RightSideFsm,
)
from scripts.metrics.pipeline import bar_hard_frozen


def test_bar_hard_frozen_or():
    assert bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 1}) is True
    assert bar_hard_frozen({"is_st": 1, "hard_freeze_flag": 0}) is True
    assert bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 0}) is False


def test_hard_freeze_flag_forces_exit_untradable():
    """Spec §5.2#5: flag set + R → EXIT_RIGHT / forced_exit_untradable."""
    fsm = RightSideFsm()
    fsm.step_trade_day("热")
    events = fsm.step_trade_day(
        "热",
        hard_frozen=bar_hard_frozen({"is_st": 0, "hard_freeze_flag": 1}),
    )
    assert fsm.R is False
    assert [e["event"] for e in events] == [EVENT_EXIT]
    assert events[0]["detail"]["exit_kind"] == EXIT_KIND_UNTRADABLE


def test_load_symbol_bars_includes_flag(tmp_path):
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    ensure_bars_columns(conn)
    conn.execute(
        """
        INSERT INTO bars (
          ts_code, trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
          is_st, is_suspended, hard_freeze_flag
        ) VALUES ('000001.SZ','2024-01-08',1,1,1,1,0,0,1)
        """
    )
    conn.commit()
    rows = _load_symbol_bars(conn, "000001.SZ", dt.date(2024, 1, 8))
    assert rows and int(rows[-1]["hard_freeze_flag"]) == 1
```

- [ ] **Step 2: Implement**

`pipeline.py`:

```python
def bar_hard_frozen(bar) -> bool:
    return bool(int(bar.get("is_st") or 0)) or bool(
        int(bar.get("hard_freeze_flag") or 0)
    )

# in replay_from_ohlc loop:
hard = bar_hard_frozen(bar)
```

Update docstring: ``hard_frozen`` is ``is_st OR hard_freeze_flag``.

`daily_run.py`:

```python
_BARS_SELECT = """
SELECT trade_date, open_qfq, high_qfq, low_qfq, close_qfq,
       is_st, is_suspended, float_mv, amount, hard_freeze_flag
FROM bars
WHERE ts_code=? AND trade_date<=?
ORDER BY trade_date ASC
"""
# in _load_symbol_bars out.append:
"hard_freeze_flag": r[9],
```

- [ ] **Step 3: Bump `param_version` + whitelist pins**

In `config/metrics/a_share_daily.yaml`:

```yaml
param_version: p05-v3
```

Update only real-yaml pins:

| File | Change |
|------|--------|
| `tests/test_features.py` | `== "p05-v3"` |
| `tests/test_daily_run_metrics_wire.py` | `"p05-v2"` → `"p05-v3"` |
| `tests/test_hard_freeze_config.py` | assert `param_version == "p05-v3"` |

Do **not** change fixture hardcodes in `tests/test_digest_rs_vol.py`.

- [ ] **Step 4: Pytest**

Run: `.venv/bin/pytest tests/test_pipeline_hard_freeze_flag.py tests/test_fsm.py tests/test_features.py tests/test_daily_run_metrics_wire.py tests/test_hard_freeze_config.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics/pipeline.py scripts/daily_run.py config/metrics/a_share_daily.yaml \
  tests/test_pipeline_hard_freeze_flag.py tests/test_features.py \
  tests/test_daily_run_metrics_wire.py tests/test_hard_freeze_config.py
git commit -m "$(cat <<'EOF'
feat(metrics): OR hard_freeze_flag into hard_frozen; bump p05-v3

EOF
)"
```

---

### Task 6: Pass `limit_up_unfillable` + write `limit_rule` on summary

**Files:**
- Modify: `scripts/eval/live_shadow_step.py`
- Modify: `scripts/eval/paper_book.py` (`fill_day` calls + `window_kpis` / `_write_out`)
- Modify: `scripts/eval/fill_day.py` only if `round_kpis` is the summary path used — prefer attaching meta on `window_kpis` / `_write_out`
- Test: `tests/test_fill_day.py`, `tests/test_eval_costs_book.py` or new assert on summary keys

**Interfaces:**
- Consumes: `EvalCosts.limit_up_unfillable`, `EvalCosts.limit_rule`, `EvalCosts.cost_version`
- Produces: `fill_day(..., limit_up_unfillable=costs.limit_up_unfillable)`; `summary.json` includes `limit_rule` + `cost_version`

- [ ] **Step 1: Grep callers**

```bash
rg -n "fill_day\(" scripts/eval --glob '*.py'
```

- [ ] **Step 2: Wire fill_day (exact call sites)**

`scripts/eval/paper_book.py` `replay_window`:

```python
        fills = fill_day(
            T.isoformat(),
            sigs,
            book,
            bars,
            costs,
            track="H",
            run_id=run_id,
            limit_up_unfillable=costs.limit_up_unfillable,
        )
```

`scripts/eval/live_shadow_step.py`:

```python
    fills = fill_day(
        T,
        pending,
        book,
        bars,
        costs,
        track="L",
        param_version=param_v,
        map_version=map_v,
        run_id="shadow-%s" % T,
        skip_event_days=paper_fill_keys_on_date(conn, T),
        limit_up_unfillable=costs.limit_up_unfillable,
    )
```

- [ ] **Step 3: Summary meta from payload costs**

`replay_window` return:

```python
    return {"fills": all_fills, "kpi": kpi, "book": book, "costs": costs}
```

`_write_out`:

```python
    kpi = dict(payload["kpi"])
    costs = payload["costs"]
    kpi["limit_rule"] = costs.limit_rule
    kpi["cost_version"] = costs.cost_version
    with open(os.path.join(dest, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)
```

Any CLI/`main` that calls `_write_out` must pass the enriched payload (already returned by `replay_window`).

- [ ] **Step 4: Tests**

```python
def test_limit_up_sell_still_fills_when_unfillable_false():
    """Mirror test_fill_forced_exit_st setup; open at limit_up; unfillable false → filled."""
    from datetime import date
    from scripts.common.calendar import load_trade_dates_from_list
    from scripts.eval.book import BookState
    from scripts.eval.costs import load_costs
    from scripts.eval.fill_day import fill_day

    load_trade_dates_from_list(["2024-01-05", "2024-01-08", "2024-01-09"])
    costs = load_costs()
    assert costs.limit_up_unfillable is False
    book = BookState(cash=costs.initial_cash, last_equity=costs.initial_cash)
    fill_day(
        "2024-01-08",
        [{"event": "ENTER_RIGHT", "ts_code": "000001.SZ", "trade_date": "2024-01-05", "id": 1, "RS": 1}],
        book,
        {"000001.SZ": {
            "open_raw": 10.0, "close_raw": 10.0,
            "limit_up": 11.0, "limit_down": 9.0, "is_suspended": 0,
        }},
        costs,
        limit_up_unfillable=costs.limit_up_unfillable,
    )
    fills = fill_day(
        "2024-01-09",
        [{
            "event": "EXIT_RIGHT",
            "ts_code": "000001.SZ",
            "trade_date": "2024-01-08",
            "id": 3,
            "detail": {"exit_kind": "temperature"},
        }],
        book,
        {"000001.SZ": {
            "open_raw": 11.0, "close_raw": 11.0,
            "limit_up": 11.0, "limit_down": 9.0, "is_suspended": 0,
        }},
        costs,
        limit_up_unfillable=False,
    )
    sold = [f for f in fills if f["side"] == "sell" and f["status"] == "filled"]
    assert len(sold) == 1


def test_summary_includes_limit_rule_and_cost_version(tmp_path):
    """Must go through _write_out(payload with costs) — do not pre-stuff kpi keys."""
    import json
    from datetime import date
    from scripts.common.calendar import load_trade_dates_from_list
    from scripts.eval.costs import load_costs
    from scripts.eval.paper_book import replay_window, _write_out

    load_trade_dates_from_list(["2024-01-05", "2024-01-08"])
    costs = load_costs()
    payload = replay_window(
        date(2024, 1, 5),
        date(2024, 1, 8),
        signals=[],
        bars_by_day={},
        costs=costs,
        run_id="sum-meta",
    )
    assert "costs" in payload
    _write_out(str(tmp_path), "t", payload)
    summary = json.loads((tmp_path / "t" / "summary.json").read_text())
    assert summary["limit_rule"] == "board_calc_v1"
    assert summary["cost_version"] == "v2"
```

- [ ] **Step 5: Pytest + commit**

Run: `.venv/bin/pytest tests/test_fill_day.py -q`  
Expected: PASS

```bash
git add scripts/eval/live_shadow_step.py scripts/eval/paper_book.py tests/test_fill_day.py
git commit -m "$(cat <<'EOF'
feat(fill): thread limit_up_unfillable and summary limit_rule

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
| summary `limit_rule` + `cost_version` | 6 (via payload `costs`, not pre-stuffed kpi) |
| `cost_version` bump | 0 |
| `param_version` bump | 5 (after freeze+OR) |
| `hard_freeze_flag` ensure + CREATE | 1 |
| streak N=20, holes, resume clear | 2 (`apply_*` only) |
| full-U rewrite; N mid-state + rewrite | 2 |
| passes before `conn.close`; full mapped U; incomplete+`complete=False` | 4 |
| CLI `session_asof`≠`--end`; `--asof` drives `with_limits` compare | 4 |
| metrics OR flag; daily_run SELECT; flag→forced_exit | 5 |
| docs touchpoints | 7 |
| Actions workflow | no change |

Indep plan CR patch (2026-10-08): `conn.close` order; full-U passes; #2b/#10/#11; drop brittle escape; defer `p05-v3`; non-tautological summary test.

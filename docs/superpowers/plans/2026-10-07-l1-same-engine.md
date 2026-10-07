# L1 Same-Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close metrics §10.4 / C5 for L1: member-closure once → synthetic OHLC → same FSM as stocks/L2; split L1 `tag_warm_to_hot` from `warm_to_hot_member_count`; minimal digest/Radar alignment.

**Architecture:** Generalize L2 `synthesize_l2_bars` + `_l2_asof_row` into basket-agnostic helpers keyed by YAML `member_set`. `replay_metrics_cross_section` keeps L2 path, then runs the same synth→replay for each non-empty L1 closure (shared `bar_cache`/`dates`). Stop calling `aggregate_l1` for production `daily_l1` rows. Digest adds `## L1 自身`; Radar renames 温转热→个股温转热.

**Tech Stack:** Python 3.11, sqlite3, PyYAML, pytest (no new deps).

## Global Constraints

- Spec: [`2026-10-07-l1-same-engine-design.md`](../specs/2026-10-07-l1-same-engine-design.md) (CR patches applied)
- Formula source of truth = L2 spec §3 (do not fork math)
- Density/amount: `ts_code ∈ YAML member_set` only (not `l1_id` / `sw_l2_code` field)
- Full `stock_rows` into asof helper; never `tradable_rows` only
- YAML closure non-empty → always upsert `daily_l1` (ban `if members_tradable` drop)
- No L1 `signal_event`; `S_temp`/`RS` stay NULL; no lookback truncation; no `engine_state`
- Do not commit `data/heartbeat.json` / dirty `trade_dates.json` in feat commits
- L2 regression must stay green after shared-helper refactor

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/metrics/l2_synth.py` | Add `synthesize_basket_bars`; keep `synthesize_l2_bars` as thin alias |
| `scripts/daily_run.py` | `_basket_asof_row` (member_set); L1 wire; drop `aggregate_l1` write path |
| `scripts/metrics/aggregate.py` | Optional rename `stub_l1_members`→`l1_members_map` alias; keep `member_closure` |
| `scripts/issues/digest.py` | `## L1 自身` block; Radar header + footnote |
| `tests/test_basket_asof_row.py` | Density member_set fixtures (L1+L2) |
| `tests/test_c5_same_engine.py` | Extend L1 C5; keep L2 |
| `tests/test_l1_daily_run_wire.py` | Skip-day, anti-nest runtime, no members_tradable drop |
| `tests/test_l1_digest.py` | L1 自身 + Radar copy |
| `docs/superpowers/specs/2026-10-07-l1-same-engine-design.md` | Status → shipped + plan link |
| `docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md` | Already revised for member_set / Spec B pointer — include in Task 0 commit if dirty |
| `README.md` / `todo.md` | Spec B done |

```text
Task 0 (docs) ─► Task 1 (synth alias + asof helper)
                      │
                      ├─► Task 2 (daily_run L1 wire + anti-nest/skip)
                      │         └─► Task 3 (C5 L1)
                      └─► Task 4 (digest) ─► Task 5 (done-when)
```

---

### Task 0: Docs authority commit

**Files:**
- Modify: `docs/superpowers/specs/2026-10-07-l1-same-engine-design.md` (status line → 设计已审；plan 链接)
- Modify: `docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md` (if uncommitted CR sync)
- Create: `docs/superpowers/plans/2026-10-07-l1-same-engine.md` (this file)
- Modify: `todo.md` (Spec B → plan ready)

**Interfaces:** none

- [ ] **Step 1: Point status + todo at this plan**

Working tree may already have status/todo edits — verify then commit. Target:

```markdown
**状态：** 设计已审；plan [`2026-10-07-l1-same-engine.md`](../plans/2026-10-07-l1-same-engine.md)
```

`todo.md` Spec B row: **plan 就绪** + links to spec/plan.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-10-07-l1-same-engine-design.md \
  docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md \
  docs/superpowers/plans/2026-10-07-l1-same-engine.md todo.md
git commit -m "$(cat <<'EOF'
docs: Spec B L1 same-engine design + implementation plan

EOF
)"
```

---

### Task 1: Basket synth alias + `member_set` asof helper

**Files:**
- Modify: `scripts/metrics/l2_synth.py`
- Modify: `scripts/daily_run.py` (`_l2_asof_row` → `_basket_asof_row`, L2 call sites)
- Test: `tests/test_basket_asof_row.py` (new)
- Regression: `tests/test_l2_synth.py`, `tests/test_c5_same_engine.py`, `tests/test_l2_daily_run_wire.py`

**Interfaces:**
- Produces: `synthesize_basket_bars(member_bars_by_ts, *, trade_dates) -> list[dict]`
- Produces: `synthesize_l2_bars = synthesize_basket_bars` (alias)
- Produces: `_basket_asof_row(code, members, stock_rows, snap, *, trade_date, members_total) -> dict`  
  Density/amount only when `r["ts_code"] in member_set`.

- [ ] **Step 1: Failing density tests**

Create `tests/test_basket_asof_row.py`:

```python
from scripts.daily_run import _basket_asof_row


def test_count_uses_member_set_not_sw_l2_field():
    members = ["000001.SZ"]
    rows = [
        {
            "ts_code": "000001.SZ",
            "sw_l2_code": "WRONG",
            "l1_id": None,
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
        {
            "ts_code": "000002.SZ",
            "sw_l2_code": "370100",
            "l1_id": "l1_health",
            "tag_warm_to_hot": 1,
            "amount": 2e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
    ]
    out = _basket_asof_row(
        "370100",
        members,
        rows,
        snap=None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert out["warm_to_hot_member_count"] == 1
    assert out["amount"] == 1e8
    assert out["T"] is None
    assert out["tag_warm_to_hot"] is None


def test_l1_count_ignores_l1_id_outside_closure():
    members = ["000001.SZ"]
    rows = [
        {
            "ts_code": "000001.SZ",
            "l1_id": "other",
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
        {
            "ts_code": "999999.SZ",
            "l1_id": "l1_health",
            "tag_warm_to_hot": 1,
            "amount": 9e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
    ]
    out = _basket_asof_row(
        "l1_health",
        members,
        rows,
        snap=None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert out["warm_to_hot_member_count"] == 1
    assert out["amount"] == 1e8


def test_l1_density_only_accepts_stock_rows_not_l2_payload():
    """Spec §7.3: L2 industry tag must not feed L1 density.

    `_basket_asof_row` has no daily_l2 parameter — lock by API + cool stocks → 0.
    Also reject accidental 'code' keys that look like L2 baskets in stock_rows.
    """
    import inspect
    from scripts.daily_run import _basket_asof_row as fn

    assert "daily_l2" not in inspect.signature(fn).parameters
    members = ["000001.SZ"]
    rows = [
        {
            "ts_code": "000001.SZ",
            "tag_warm_to_hot": 0,
            "amount": 1e8,
            "hard_frozen": False,
            "_is_suspended": False,
        },
        # decoy: looks like an L2 basket row mistakenly mixed into stock_rows
        {
            "code": "370100",
            "tag_warm_to_hot": 1,
            "amount": 9e9,
        },
    ]
    out = fn(
        "l1_health",
        members,
        rows,
        snap=None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert out["warm_to_hot_member_count"] == 0
    assert out["amount"] == 1e8
```

- [ ] **Step 2: Run — expect fail**

```bash
python3 -m pytest tests/test_basket_asof_row.py -v --tb=short
```

Expected: FAIL (`_basket_asof_row` missing and/or old `sw_l2_code==code` counts 000002).

- [ ] **Step 3: Implement synth alias + helper**

In `l2_synth.py`: rename body function to `synthesize_basket_bars`; add:

```python
synthesize_l2_bars = synthesize_basket_bars
```

In `daily_run.py`: replace `_l2_asof_row` with the full helper (no omitted body):

```python
def _basket_asof_row(
    code: str,
    members: Sequence[str],
    stock_rows: Sequence[Mapping],
    snap: Mapping | None,
    *,
    trade_date: str,
    members_total: int,
) -> dict:
    """Build one daily_l1/l2 row: engine from snap; count/amount via member_set."""
    member_set = set(members)
    warm_count = 0
    amount_sum = 0.0
    any_amount = False
    members_tradable = 0
    for r in stock_rows:
        ts = r.get("ts_code")
        if ts in member_set:
            if r.get("tag_warm_to_hot"):
                warm_count += 1
            amt = _sql_float(r.get("amount"))
            if amt is not None:
                amount_sum += amt
                any_amount = True
            if not r.get("hard_frozen") and not r.get("_is_suspended"):
                members_tradable += 1
    if snap is None:
        t = None
        right_side = None
        tag_hot = None
        tag_flat = None
        solar = None
    else:
        t = snap.get("T")
        right_side = int(bool(snap.get("R")))
        tag_hot = int(bool(snap.get("tag_warm_to_hot")))
        tag_flat = int(bool(snap.get("tag_warm_to_flat")))
        solar = snap.get("solar_term")
    return {
        "trade_date": trade_date,
        "code": code,
        "T": t,
        "S_temp": None,
        "RS": None,
        "right_side": right_side,
        "tag_warm_to_hot": tag_hot,
        "tag_warm_to_flat": tag_flat,
        "solar_term": solar,
        "members_tradable": members_tradable,
        "members_total": members_total,
        "warm_to_hot_member_count": warm_count,
        "amount": amount_sum if any_amount else None,
    }


_l2_asof_row = _basket_asof_row  # compat for tests / call sites
```

Point L2 loop at `_basket_asof_row` + `synthesize_basket_bars` (or alias).

Update `tests/test_l2_daily_run_wire.py` member lists to still pass under `member_set` counting (rows already use `ts_code` in members — OK). If any test relied on counting via `sw_l2_code` alone without `ts_code` in members, fix the fixture to put `ts_code` in `members`.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_basket_asof_row.py tests/test_l2_synth.py \
  tests/test_c5_same_engine.py tests/test_l2_daily_run_wire.py -q --tb=line
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics/l2_synth.py scripts/daily_run.py tests/test_basket_asof_row.py
git commit -m "$(cat <<'EOF'
refactor(metrics): basket synth + member_set asof helper for L1/L2

EOF
)"
```

---

### Task 2: `daily_run` L1 same-engine wire

**Files:**
- Modify: `scripts/daily_run.py` (`replay_metrics_cross_section`)
- Test: `tests/test_l1_daily_run_wire.py` (new)

**Interfaces:**
- Consumes: `synthesize_basket_bars`, `_basket_asof_row`, `stub_l1_members` / `member_closure`, shared `bar_cache`/`dates`
- Produces: `l1_rows` from synth→replay; no `aggregate_l1(...)` in this function for writes

- [ ] **Step 1: Failing wire tests**

Create `tests/test_l1_daily_run_wire.py` (full content):

```python
"""L1 daily_run wire: no aggregate_l1; skip-day NULL; tag ≠ member OR."""
from __future__ import annotations

from datetime import date

from scripts.common.bars import bars_conn
from scripts.daily_run import _basket_asof_row, replay_metrics_cross_section
from tests.test_daily_run_metrics_wire import (
    SHORT_N,
    _seed_uptrend,
    _short_params,
    _weekdays_ending,
)


def _stub_l1_taxonomy(monkeypatch):
    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    for mod in (
        "scripts.common.universe.l2_members_map",
        "scripts.daily_run.l2_members_map",
        "scripts.metrics.aggregate.l2_members_map",
    ):
        monkeypatch.setattr(mod, lambda: {"370100": ["000001.SZ"]})
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )
    monkeypatch.setattr(
        "scripts.common.universe.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )


def test_l1_skip_day_null_engine_fields():
    stock_rows = [
        {
            "ts_code": "A.SZ",
            "l1_id": "wrong",
            "tag_warm_to_hot": 1,
            "amount": 1e8,
            "hard_frozen": 0,
            "_is_suspended": False,
        },
    ]
    row = _basket_asof_row(
        "l1_test",
        ["A.SZ"],
        stock_rows,
        None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert row["T"] is None and row["right_side"] is None
    assert row["tag_warm_to_hot"] is None
    assert row["warm_to_hot_member_count"] == 1
    assert row["members_tradable"] == 1


def test_l1_tag_not_or_of_members():
    cool_snap = {
        "T": "凉",
        "R": False,
        "tag_warm_to_hot": False,
        "tag_warm_to_flat": False,
        "solar_term": None,
    }
    stock_rows = [
        {"ts_code": "A.SZ", "tag_warm_to_hot": 0, "amount": 1e8},
        {"ts_code": "B.SZ", "tag_warm_to_hot": 1, "amount": 2e8},
    ]
    row = _basket_asof_row(
        "l1_test",
        ["A.SZ", "B.SZ"],
        stock_rows,
        cool_snap,
        trade_date="2024-01-10",
        members_total=2,
    )
    assert row["tag_warm_to_hot"] == 0
    assert row["warm_to_hot_member_count"] == 1


def test_l1_wire_does_not_call_aggregate_l1(tmp_path, monkeypatch):
    from scripts import daily_run as dr

    def boom(*a, **k):
        raise AssertionError("aggregate_l1 must not be used for L1 write path")

    monkeypatch.setattr(dr, "aggregate_l1", boom)
    _stub_l1_taxonomy(monkeypatch)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()
    _s, _l2, l1_rows, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "l1_test" for r in l1_rows)
    assert not any(e.get("ts_code") == "l1_test" for e in events)


def test_l1_synth_uses_member_closure_stock_bars_not_daily_l2(tmp_path, monkeypatch):
    """Spec §7.4 runtime: synth keys == closure; no daily_l2 price feed."""
    from scripts import daily_run as dr
    from scripts.metrics.aggregate import member_closure

    _stub_l1_taxonomy(monkeypatch)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    captured = {}
    real_synth = dr.synthesize_basket_bars

    def spy_synth(member_bars, *, trade_dates):
        captured["keys"] = sorted(member_bars.keys())
        captured["dates"] = list(trade_dates)
        for ts, rows in member_bars.items():
            assert rows, ts
            assert "close_qfq" in rows[0]
            assert "code" not in rows[0]  # stock bars, not daily_l2 rows
        return real_synth(member_bars, trade_dates=trade_dates)

    monkeypatch.setattr(dr, "synthesize_basket_bars", spy_synth)
    # if still imported as synthesize_l2_bars alias in module, patch that too
    if hasattr(dr, "synthesize_l2_bars"):
        monkeypatch.setattr(dr, "synthesize_l2_bars", spy_synth)

    _s, _l2, l1_rows, _e = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "l1_test" for r in l1_rows)
    expected = sorted(member_closure(["370100"], {"370100": ["000001.SZ"]}))
    assert captured["keys"] == expected


def test_l1_helper_members_tradable_zero_still_has_keys():
    row = _basket_asof_row(
        "l1_test",
        ["A.SZ"],
        [
            {
                "ts_code": "A.SZ",
                "tag_warm_to_hot": 0,
                "amount": None,
                "hard_frozen": True,
                "_is_suspended": False,
            }
        ],
        None,
        trade_date="2024-01-10",
        members_total=1,
    )
    assert row["members_tradable"] == 0
    assert row["code"] == "l1_test"
    assert "T" in row and row["T"] is None


def test_l1_wire_keeps_row_when_members_tradable_zero(tmp_path, monkeypatch):
    """Ban production `if members_tradable` filter — assert on wire return list."""
    from scripts import daily_run as dr

    _stub_l1_taxonomy(monkeypatch)
    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 8)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    conn.close()

    seen = {}
    real_basket = dr._basket_asof_row

    def tracking_basket(code, members, stock_rows, snap, **kw):
        frozen = []
        for r in stock_rows:
            rr = dict(r)
            if rr.get("ts_code") in set(members):
                rr["hard_frozen"] = True
            frozen.append(rr)
        out = real_basket(code, members, frozen, snap, **kw)
        if code == "l1_test":
            seen["row"] = out
        return out

    monkeypatch.setattr(dr, "_basket_asof_row", tracking_basket)
    monkeypatch.setattr(dr, "_l2_asof_row", tracking_basket)
    _s, _l2, l1_rows, _e = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=_short_params(),
        universe=["000001.SZ"],
    )
    assert any(r["code"] == "l1_test" for r in l1_rows), (
        "YAML closure non-empty must keep L1 row even when members_tradable=0"
    )
    assert seen["row"]["members_tradable"] == 0
```

- [ ] **Step 2: Run — expect fail (wire-only)**

```bash
python3 -m pytest tests/test_l1_daily_run_wire.py -v --tb=short
```

Expected after Task 1: helper tests may PASS; wire tests FAIL until Task 2 lands:
`test_l1_wire_does_not_call_aggregate_l1`, `test_l1_wire_keeps_row_when_members_tradable_zero`, `test_l1_synth_uses_member_closure_stock_bars_not_daily_l2`.

- [ ] **Step 3: Wire L1 after L2 loop**

Replace the `l1_rows = [row for row in aggregate_l1(tradable_rows, td) if row.get("members_tradable")]` block with:

```python
from scripts.metrics.aggregate import stub_l1_members  # or l1_members_map
from scripts.metrics.l2_synth import synthesize_basket_bars

l1_groups = stub_l1_members()
# ensure bar_cache covers L1 closure (reuse L2-preloaded cache)
for members in l1_groups.values():
    for ts in members:
        if ts not in bar_cache:
            bar_cache[ts] = _load_symbol_bars(bconn, ts, D)
# Prefer the same `dates` list already computed for L2. Only recompute if
# L1 fill extended bar_cache to an earlier start (rare when L1 ⊆ L2 mapped set).

l1_rows = []
for l1_id, members in l1_groups.items():
    if not members:
        continue
    member_bars = {ts: bar_cache[ts] for ts in members if bar_cache.get(ts)}
    synth = synthesize_basket_bars(member_bars, trade_dates=dates)
    snap = None
    if synth:
        snaps = replay_from_ohlc(params, synth, min_history=min_hist)
        asof = [s for s in snaps if s.get("trade_date") == td]
        snap = asof[-1] if asof else None
    # NEVER append snap.event_records to events
    l1_rows.append(
        _basket_asof_row(
            l1_id,
            members,
            stock_rows,  # FULL cross-section
            snap,
            trade_date=td,
            members_total=len(members),
        )
    )
```

Remove unused `aggregate_l1` import from production path if nothing else needs it in this module (tests may still import from `aggregate`).

Update `scripts/metrics/aggregate.py` module docstring: stop claiming L1 production is forever majority/tag-any interim; note L1 same-engine lives in `daily_run` (this module may still expose `aggregate_l1` for legacy tests).

- [ ] **Step 4: Run wire + L2 regression**

```bash
python3 -m pytest tests/test_l1_daily_run_wire.py tests/test_l2_daily_run_wire.py \
  tests/test_c5_same_engine.py tests/test_basket_asof_row.py -q --tb=line
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/daily_run.py tests/test_l1_daily_run_wire.py
git commit -m "$(cat <<'EOF'
feat(daily_run): L1 same-engine synth+replay; drop aggregate_l1 write path

EOF
)"
```

---

### Task 3: C5 L1 synthetic twins

**Files:**
- Modify: `tests/test_c5_same_engine.py`

**Interfaces:**
- Consumes: L1 wire from Task 2; stubs for `l2_members_map` + `l1_to_l2_map`

- [ ] **Step 1: Failing L1 C5 test**

Append to `tests/test_c5_same_engine.py`:

```python
def test_C5_same_engine_on_synthetic_l1(tmp_path, monkeypatch):
    """Identical twin stocks in one L1 closure → L1 asof matches single-stock replay."""
    from scripts.daily_run import _load_symbol_bars, replay_metrics_cross_section
    from scripts.metrics.l2_synth import synthesize_basket_bars

    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    monkeypatch.setattr(
        "scripts.daily_run.taxonomy_for_stock",
        lambda ts, **kw: ("370100", "l1_test"),
    )
    monkeypatch.setattr(
        "scripts.common.universe.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.daily_run.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l2_members_map",
        lambda: {"370100": ["000001.SZ", "000002.SZ"]},
    )
    monkeypatch.setattr(
        "scripts.metrics.aggregate.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )
    monkeypatch.setattr(
        "scripts.common.universe.l1_to_l2_map",
        lambda: {"l1_test": ["370100"]},
    )

    D = date(2024, 1, 10)
    dates = _weekdays_ending(D, SHORT_N + 1)
    monkeypatch.setattr(
        "scripts.daily_run.cal.trading_days_inclusive",
        lambda start, end: [d for d in dates if start <= d <= end],
    )
    bars_path = str(tmp_path / "bars.db")
    conn = bars_conn(bars_path)
    _seed_uptrend(conn, "000001.SZ", dates, start_px=10.0)
    _seed_uptrend(conn, "000002.SZ", dates, start_px=20.0)
    conn.close()

    params = _short_params()
    _stock, _l2, l1_rows, events = replay_metrics_cross_section(
        D,
        bars_path=bars_path,
        params=params,
        universe=["000001.SZ", "000002.SZ"],
    )
    l1 = next(r for r in l1_rows if r["code"] == "l1_test")
    assert l1["T"] is not None

    bconn = bars_conn(bars_path)
    stock_bars = _load_symbol_bars(bconn, "000001.SZ", D)
    twin_bars = _load_symbol_bars(bconn, "000002.SZ", D)
    bconn.close()
    synth = synthesize_basket_bars(
        {"000001.SZ": stock_bars, "000002.SZ": twin_bars},
        trade_dates=dates,
    )
    snaps = replay_from_ohlc(params, synth, min_history=SHORT_N)
    expected = [s for s in snaps if s.get("trade_date") == D.isoformat()][-1]

    assert l1["T"] == expected.get("T")
    assert l1["right_side"] == int(bool(expected.get("R")))
    assert l1["tag_warm_to_hot"] == int(bool(expected.get("tag_warm_to_hot")))
    assert l1["tag_warm_to_flat"] == int(bool(expected.get("tag_warm_to_flat")))
    assert l1["solar_term"] == expected.get("solar_term")
    assert not any(e.get("ts_code") == "l1_test" for e in events)
```

- [ ] **Step 2: Run**

```bash
python3 -m pytest tests/test_c5_same_engine.py -v --tb=short
```

Expected: L2 still PASS; L1 PASS after Task 2 (if Task 2 incomplete, FAIL until wire lands — run this task after Task 2).

- [ ] **Step 3: Commit**

```bash
git add tests/test_c5_same_engine.py
git commit -m "$(cat <<'EOF'
test(c5): assert L1 same-engine matches twin-stock replay

EOF
)"
```

---

### Task 4: Digest `## L1 自身` + Radar copy

**Files:**
- Modify: `scripts/issues/digest.py`
- Test: `tests/test_l1_digest.py` (extend or add cases)

**Interfaces:**
- Consumes: `daily_l1` row for `code=l1_id`; `load_l1_buckets` names
- Produces: markdown with exact `## L1 自身`; Radar header `个股温转热` + footnote

- [ ] **Step 1: Failing digest tests**

Extend `tests/test_l1_digest.py`: import `upsert_daily_l1`; add to `_seed` (or a dedicated seed) a `daily_l1` row for `l1_finance` with `RS=None`, `tag_warm_to_hot=0`, `warm_to_hot_member_count=1`, `amount=1e9`. Then:

```python
from scripts.common.db import upsert_daily_l1


def _seed_with_daily_l1(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    upsert_daily_l1(
        conn,
        [
            {
                "trade_date": td,
                "code": "l1_finance",
                "T": "凉",
                "S_temp": None,
                "RS": None,
                "right_side": 0,
                "tag_warm_to_hot": 0,
                "tag_warm_to_flat": 0,
                "solar_term": None,
                "members_tradable": 1,
                "members_total": 2,
                "warm_to_hot_member_count": 1,
                "amount": 1e9,
            }
        ],
    )
    conn.commit()
    return conn, td


def test_l1_issue_has_self_section(tmp_path, monkeypatch):
    conn, td = _seed_with_daily_l1(tmp_path, monkeypatch)
    md = render_l1_issue(conn, td, "l1_finance", name_zh="金融")
    assert "## L1 自身" in md
    head = md.split("## 行业")[0]
    assert "同引擎" not in head
    assert "成分温转热" in head
    # RS NULL → empty cell (pipe with nothing between separators in RS column)
    assert "| 凉 | l1_finance | 金融 |  | " in md or "| 凉 | l1_finance | 金融 | |" in md
    conn.close()


def test_radar_stock_warm_header_and_footnote(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)
    md = render_radar_issue(conn, td, load_l1_buckets())
    # Lock TABLE header (footnote alone must not satisfy)
    assert "| L1 | l1_id | T* | 个股 | 右侧 | 右侧占比 | 个股温转热 |" in md
    assert "按 l1_id" in md
    assert "L1 自身" in md
    conn.close()


def test_l1_self_section_empty_when_no_daily_l1_row(tmp_path, monkeypatch):
    conn, td = _seed(tmp_path, monkeypatch)  # no upsert_daily_l1
    md = render_l1_issue(conn, td, "l1_health", name_zh="医药健康")
    assert "## L1 自身" in md
    head = md.split("## 行业")[0]
    assert "成分温转热" in head
    # must not crash; engine cells empty — no fabricated 0 for tag
    assert "同引擎" not in head
    conn.close()
```

- [ ] **Step 2: Run — expect fail**

```bash
python3 -m pytest tests/test_l1_digest.py -k "self_section or stock_warm" -v --tb=short
```

- [ ] **Step 3: Implement**

In `render_l1_issue`, before `## 行业（L2）扫描`:

```python
lines.append("## L1 自身")
row = conn.execute(
    """
    SELECT T, RS, right_side, solar_term, tag_warm_to_hot,
           warm_to_hot_member_count, amount
    FROM daily_l1 WHERE trade_date=? AND code=?
    """,
    (td, l1_id),
).fetchone()
# Spec §5.1 headers exactly:
headers = ["T", "l1_id", "名称", "RS", "右侧", "节气", "温转热", "成分温转热", "成交额(亿)"]
if row is None:
    cells = ["", l1_id, name_zh, "", "", "", "", "", ""]
else:
    t, rs, right, solar, tag, wcount, amt = row
    cells = [
        "" if t is None else t,
        l1_id,
        name_zh,
        "" if rs is None else rs,  # NULL → empty, never 0
        "" if right is None else right,
        "" if solar is None else solar,
        "" if tag is None else tag,
        0 if wcount is None else wcount,  # count defaults 0 when row exists but null
        _fmt_amount_yi(amt),
    ]
lines.extend(_md_table(headers, [tuple(cells)]))
lines.append("")
```

When `row is None`, `成分温转热` cell is `""` (not 0) — matches “引擎列空”.

In `render_radar_issue`, change the **table** headers list from `温转热` to `个股温转热`, then append footnote after the L1 table:

```python
lines.append(
    "T* / 个股温转热 = 个股截面（按 l1_id），非 L1 同引擎；"
    "L1 自身（含 YAML 闭包「成分温转热」）见各 L1 Issue「L1 自身」。"
)
```

- [ ] **Step 4: Run**

```bash
python3 -m pytest tests/test_l1_digest.py -q --tb=line
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/issues/digest.py tests/test_l1_digest.py
git commit -m "$(cat <<'EOF'
feat(digest): L1 self row + Radar 个股温转热 label

EOF
)"
```

---

### Task 5: Done-when docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-07-l1-same-engine-design.md` (状态 → 已落地)
- Modify: `todo.md`, `README.md`
- Verify L2 spec pointer sentences already match §9 (from CR)

**Interfaces:** none

- [ ] **Step 1: Full test gate**

```bash
python3 -m pytest tests/test_basket_asof_row.py tests/test_l1_daily_run_wire.py \
  tests/test_c5_same_engine.py tests/test_l2_daily_run_wire.py tests/test_l2_synth.py \
  tests/test_l1_digest.py -q --tb=line
```

Expected: all PASS. Then broader:

```bash
python3 -m pytest -q --tb=line
```

Expected: full suite green (or document any pre-existing unrelated fails — do not ignore new fails).

- [ ] **Step 2: Docs**

- Spec B status: **已落地** + plan link  
- `todo.md`: Spec B **已完成**; §2.1 mark done; next = Spec C  
- `README.md`: L1 same-engine shipped; remove "same-engine L1" from Still out  
- L2 spec §6 error table: delete/replace residual row `L1 tag-any | 保持…` with pointer to Spec B (see already-patched §2.1; keep §6 in sync)

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-07-l1-same-engine-design.md \
  docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md \
  todo.md README.md scripts/metrics/aggregate.py
git commit -m "$(cat <<'EOF'
docs: mark Spec B L1 same-engine ready for ship

EOF
)"
```

---

## Spec coverage (self-check)

| Spec § | Task |
|--------|------|
| §2.1 density member_set | T1, T2 |
| §3 synth shared / no nest | T1, T2, T3 |
| §3.1 bar_cache reuse/fill | T2 |
| §3.1 ban members_tradable drop | T2 |
| §3.1 ban aggregate_l1 write | T2 |
| §3.1 no L1 signal_event | T2, T3 |
| §5 L1 自身 / Radar | T4 |
| §7 C5 L1 + density fixtures + L2 regression | T1–T3 |
| §9 doc sync | T0, T5 |
| Replay cost / RS / full-A | Out — no task |

## Out of this plan

- L2/L1 replay performance / `engine_state`
- Spec C RS / Spearman / C1
- Radar numeric equality with YAML-closure count
- Committing local `heartbeat.json`

## Plan CR revision

| 日期 | 说明 |
|------|------|
| 2026-10-07 | 补全 `_basket_asof_row`；wire 测 `members_tradable=0`；digest 完整种子；L2-tag 不计密度；双 stub `l1_to_l2_map`；T2 Expected 文案 |
| 2026-10-07 | subagent CR：反嵌套 runtime spy；Radar 锁表头；digest 空行+满表；dates 复用 L2；aggregate docstring；L2 §6 tag-any 行改指 Spec B |

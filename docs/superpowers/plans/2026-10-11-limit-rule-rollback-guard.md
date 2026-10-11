# limit_rule rollback hard gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `costs.limit_rule == vendor_fields` and `bars.db` still has any bilateral non-null `limit_source=board_calc_v1` row, hard-fail `live_shadow_step.run_asof` before `fill_day` (whole-DB EXISTS; no auto-clear).

**Architecture:** Shared `check_limit_rule_bars(bars_path, limit_rule)`; wire in `run_asof` after the incomplete-asof sync_status gate and immediately before `fill_day`; optional CLI.

**Tech Stack:** Python 3.11, SQLite `bars`, pytest, existing `EvalCosts` / `LIMIT_SOURCE_BOARD_CALC`.

## Global Constraints

- Spec: [`2026-10-11-limit-rule-rollback-guard-design.md`](../specs/2026-10-11-limit-rule-rollback-guard-design.md)
- Prerequisite / same-PR: incomplete plan [`2026-10-11-incomplete-asof-authority.md`](2026-10-11-incomplete-asof-authority.md) **Tasks 0–2 landed** (sync_status gate already in `run_asof`)
- Whole-DB `EXISTS` (no fill-window filter); ops must clear before rollback
- `bars_path` must be the same path used for `load_ohlc_limits` / `--bars-db`
- Missing / unreadable `bars_path` → check returns **1** (fail-closed)
- Gate only `run_asof` (direct call, not `main`-only); **not** `paper_book` / `daily_run`
- **No** env bypass for this gate (`TRENDING_*` must not green it)
- `costs = load_costs()` already runs before bars/fill in `run_asof` — **keep**; place both gates after 0-skips, immediately before `fill_day` (no reorder needed)
- Integration tests **must plant fresh sync_status** (or monkeypatch sync check→0) so incomplete gate does not mask limit_rule failures
- Prefer `.venv/bin/pytest`; no dirty `data/cache/*` commits

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/eval/limit_rule_guard.py` (new) | `check_limit_rule_bars` |
| `scripts/eval/live_shadow_step.py` | call after sync_status check, before `fill_day` |
| `scripts/check_limit_rule_bars.py` (optional CLI) | thin wrapper |
| `tests/test_limit_rule_guard.py` | EXISTS matrix + homology + stderr + no-env-bypass |
| `tests/test_live_shadow_limit_rule_gate.py` | direct `run_asof` integration |
| Specs / todo / Spec E or ops | Done-when (both P0) |

```text
Task 0 (check_limit_rule_bars + unit tests)
  └─► Task 1 (wire run_asof after sync_status gate)
        └─► Task 2 (docs + todo + both Spec statuses + joint regression)
```

**Wire order in `run_asof` (钉死):**

```text
… 0-skips (calendar / live_allowed / missing_bars) …
→ check_sync_complete_for_fill(fill_asof=T)     # incomplete Spec
→ check_limit_rule_bars(bars_path, costs.limit_rule)
→ fill_day(...)
```

---

### Task 0: `check_limit_rule_bars` + unit tests

**Files:**
- Create: `scripts/eval/limit_rule_guard.py`
- Create: `tests/test_limit_rule_guard.py`

**Interfaces:**
- Produces: `check_limit_rule_bars(bars_path: str, limit_rule: str) -> int`  # 0 ok, 1 fail
- Predicate: if `limit_rule != "vendor_fields"` → 0; else if bars unreadable/missing → 1; else EXISTS bilateral `limit_source=LIMIT_SOURCE_BOARD_CALC` → 1
- On fail: print Spec stderr to stderr (must include clear / `board_calc_v1` / `cost_version`)

- [ ] **Step 1: Failing tests**
  - vendor + one board_calc bilateral row → 1
  - vendor + empty / only vendor sources → 0
  - board_calc_v1 rule + board_calc rows → 0
  - one-sided limit_up only with board_calc source → 0
  - missing bars path → 1
  - two temp DBs: check dirty path A → 1, clean path B → 0
  - fail stderr contains actionable tokens
  - with `TRENDING_ALLOW_INCOMPLETE_FILL=1` (and/or other `TRENDING_*`) still FAIL on vendor+residue (no bypass)

- [ ] **Step 2: Implement**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_limit_rule_guard.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(eval): check_limit_rule_bars for vendor vs board_calc residue

EOF
)"
```

---

### Task 1: Wire `run_asof`

**Files:**
- Modify: `scripts/eval/live_shadow_step.py`
- Create: `tests/test_live_shadow_limit_rule_gate.py`

**Interfaces:**
- After sync_status check == 0:  
  `bp = bars_path or DEFAULT_BARS_DB`  
  `rc = check_limit_rule_bars(bp, costs.limit_rule)`  
  if rc: close conn; return 1
- Keep `load_costs()` where it is today (before bars); both gates sit after `candidate_bars_ready` ok, before `fill_day`

- [ ] **Step 1: Failing integration tests** (direct `run_asof`, not only `main`)
  - **Precondition:** plant fresh SoT for fill `T` (or monkeypatch sync check→0)
  - Monkeypatch/`replace` costs → `vendor_fields`; bars fixture with board_calc row → `run_asof` returns 1; `fill_day` / `insert_paper_fills` not called
  - Same with `limit_rule=board_calc_v1` → proceeds (mock fill ok)
  - `--bars-db` / `bars_path=` dirty fails even if default DB clean (spy path arg or dual DB)

- [ ] **Step 2: Implement wire**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_live_shadow_limit_rule_gate.py tests/test_live_shadow_sync_authority.py \
  tests/test_live_shadow_gate.py tests/test_limit_rule_guard.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(shadow): hard-fail live_shadow on limit_rule vs board_calc mismatch

EOF
)"
```

---

### Task 2: Docs + todo + Spec status (both P0) + joint regression

**Files:**
- Modify: both Specs **状态** → 已落地
- Modify: `todo.md` P0 both rows → 已落地 + ops (whole-DB clear example; sync_status tip)
- Modify: Spec E short note or `docs/ops/` — rollback clear SQL example
- Optional CLI `scripts/check_limit_rule_bars.py`

- [ ] **Step 1: Docs**

- [ ] **Step 2: Focused regression**

```bash
.venv/bin/pytest tests/test_sync_status.py tests/test_limit_rule_guard.py \
  tests/test_live_shadow_sync_authority.py tests/test_live_shadow_limit_rule_gate.py \
  tests/test_live_shadow_gate.py tests/test_paper_book.py \
  tests/test_sync_hard_freeze_gate.py tests/test_p2_workflow_order.py -q
```

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: land P0 limit_rule and incomplete-asof Specs in todo

EOF
)"
```

---

## Self-review checklist

- [ ] Gate order: sync_status → limit_rule → fill_day
- [ ] Whole-DB EXISTS; missing bars fail-closed
- [ ] stderr + no env bypass tested
- [ ] Integration tests plant SoT first
- [ ] Direct `run_asof` gated (not main-only)
- [ ] `paper_book` still ungated
- [ ] Production `costs.yaml` stays `board_calc_v1` → gate idle until intentional rollback
- [ ] Both Specs + todo marked 已落地 here (same-PR end)

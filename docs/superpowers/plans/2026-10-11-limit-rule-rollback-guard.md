# limit_rule rollback hard gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `costs.limit_rule == vendor_fields` and `bars.db` still has any bilateral non-null `limit_source=board_calc_v1` row, hard-fail `live_shadow_step.run_asof` before `fill_day` (whole-DB EXISTS; no auto-clear).

**Architecture:** Shared `check_limit_rule_bars(bars_path, limit_rule)`; wire in `run_asof` after the incomplete-asof sync_status gate and immediately before `fill_day`; optional CLI.

**Tech Stack:** Python 3.11, SQLite `bars`, pytest, existing `EvalCosts` / `LIMIT_SOURCE_BOARD_CALC`.

## Global Constraints

- Spec: [`2026-10-11-limit-rule-rollback-guard-design.md`](../specs/2026-10-11-limit-rule-rollback-guard-design.md)
- Prerequisite / same-PR: incomplete plan [`2026-10-11-incomplete-asof-authority.md`](2026-10-11-incomplete-asof-authority.md) Task 2 landed (sync_status gate already in `run_asof`)
- Whole-DB `EXISTS` (no fill-window filter); ops must clear before rollback
- `bars_path` must be the same path used for `load_ohlc_limits` / `--bars-db`
- Gate only `run_asof`; **not** `paper_book` / `daily_run`
- **No** env bypass for this gate
- Do not change fill formulas or board_calc writer
- Prefer `.venv/bin/pytest`; no dirty `data/cache/*` commits

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/eval/limit_rule_guard.py` (new) | `check_limit_rule_bars` |
| `scripts/eval/live_shadow_step.py` | call after sync_status check, before `fill_day` |
| `scripts/check_limit_rule_bars.py` (optional CLI) | thin wrapper |
| `tests/test_limit_rule_guard.py` | EXISTS matrix + homology |
| `tests/test_live_shadow_limit_rule_gate.py` | run_asof integration |
| Spec E / ops note / todo / Spec status | Done-when |

```text
Task 0 (check_limit_rule_bars + unit tests)
  └─► Task 1 (wire run_asof after sync_status gate)
        └─► Task 2 (docs + todo + both Spec statuses)
```

**Wire order in `run_asof` (钉死):**

```text
… 0-skips …
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
- Predicate: if `limit_rule != "vendor_fields"` → 0; else EXISTS bilateral `limit_source='board_calc_v1'` → 1
- Use `LIMIT_SOURCE_BOARD_CALC` from `scripts.common.bars`
- On fail: print Spec stderr to stderr

- [ ] **Step 1: Failing tests**
  - vendor + one board_calc bilateral row → 1
  - vendor + empty / only vendor sources → 0
  - board_calc_v1 rule + board_calc rows → 0
  - one-sided limit_up only with board_calc source → 0 (not EXISTS)
  - two temp DBs: check path A fails, path B clean → proves path homology intent

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
- Consumes: `check_limit_rule_bars`, `load_costs` (already), `bars_path or DEFAULT_BARS_DB`
- After sync_status check returns 0: `rc = check_limit_rule_bars(bars_path or DEFAULT_BARS_DB, costs.limit_rule)`; if rc: close conn; return 1
- Ensure `costs = load_costs()` is available before this check (today costs loaded before bars — may need reorder: load costs before gates, or load earlier). Prefer: keep costs load where it is if already before `fill_day`; move sync_status + limit_rule checks to just before `fill_day` after bars ready, with `costs` already loaded.

- [ ] **Step 1: Failing integration tests**
  - Monkeypatch costs to `vendor_fields`; bars fixture with board_calc row; sync_status fresh for T → `run_asof` returns 1; `fill_day` / `insert_paper_fills` not called
  - Same with `limit_rule=board_calc_v1` → proceeds (may mock fill)
  - `--bars-db` dirty path fails even if default DB clean

- [ ] **Step 2: Implement wire**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_live_shadow_limit_rule_gate.py tests/test_live_shadow_sync_authority.py tests/test_limit_rule_guard.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(shadow): hard-fail live_shadow on limit_rule vs board_calc mismatch

EOF
)"
```

---

### Task 2: Docs + todo + Spec status (both P0)

**Files:**
- Modify: both Specs **状态** → 已落地；link plans
- Modify: `todo.md` P0 rows → 已落地 + ops notes
- Modify: Spec E short note or `docs/ops/` — rollback requires whole-DB clear example
- Optional CLI `scripts/check_limit_rule_bars.py`
- Touch Protocol B / README only if needed for cross-links

- [ ] **Step 1: Docs**

- [ ] **Step 2: Focused regression**

```bash
.venv/bin/pytest tests/test_sync_status.py tests/test_limit_rule_guard.py \
  tests/test_live_shadow_sync_authority.py tests/test_live_shadow_limit_rule_gate.py \
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
- [ ] Whole-DB EXISTS documented in stderr
- [ ] No env bypass on limit_rule
- [ ] `paper_book` still ungated
- [ ] Production `costs.yaml` remains `board_calc_v1` → gate idle until intentional rollback

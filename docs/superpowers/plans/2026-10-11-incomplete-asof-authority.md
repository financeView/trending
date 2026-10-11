# Incomplete × asof authority (sync_status + live_shadow gate) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `data/cache/sync_status.json` with pessimistic/fail-false writes; hard-fail `live_shadow_step.run_asof` when SoT is missing/incomplete/stale tip (`session_asof < fill_asof`), without breaking Spec F catch-up or Protocol B hard_freeze-fail semantics.

**Architecture:** New small module for SoT read/write + check; extend `sync_bars_sample` early/fail/success paths; gate in `run_asof` after 0-skips and immediately before `fill_day`.

**Tech Stack:** Python 3.11, pytest, JSON file SoT under `data/cache/` (gitignored).

## Global Constraints

- Spec: [`2026-10-11-incomplete-asof-authority-design.md`](../specs/2026-10-11-incomplete-asof-authority-design.md) (post re-review: `session_asof ≥ fill_asof`)
- Freshness: `sync_complete is true` **and** `session_asof` is non-empty str **and** `session_asof >= fill_asof` (YYYY-MM-DD string order). Missing/null `session_asof` → FAIL
- Gate **only** `live_shadow_step.run_asof`; **not** `paper_book` / `daily_run`
- Gate **after** `not_on_calendar` / `live_allowed` / `missing_bars` return 0; **before** `fill_day`
- `write_sync_status` = file only; `write_sync_complete` = success-end GITHUB_OUTPUT **and** final file; hard_freeze fail → `write_sync_status(false)` only, **never** `write_sync_complete`
- Atomic file write: temp + `os.replace`
- Env bypass: only `TRENDING_ALLOW_INCOMPLETE_FILL=1`; **CI / existing fill-path tests must not use it to go green** — plant SoT or monkeypatch `check_*`
- `DEFAULT_SYNC_STATUS_PATH`: `__file__`-anchored like `DEFAULT_BARS_DB` (`scripts/common/../../data/cache/sync_status.json`), **not** cwd-relative
- **Same-PR required** with [`2026-10-11-limit-rule-rollback-guard.md`](2026-10-11-limit-rule-rollback-guard.md): implement this plan Tasks 0–2 first; **defer** Spec/todo「已落地」to sister Task 2
- Do not commit `data/cache/sync_status.json`; prefer `.venv/bin/pytest`

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/sync_status.py` (new) | path constant; `write_sync_status`; `read_sync_status`; `check_sync_complete_for_fill`; atomic write |
| `scripts/sync_bars_sample.py` | early pessimistic write; fail-path status; extend `write_sync_complete(..., *, session_asof: str)` |
| `scripts/eval/live_shadow_step.py` | call check before `fill_day` |
| `tests/test_sync_status.py` | SoT + freshness matrix |
| `tests/test_sync_hard_freeze_gate.py` | spies accept `session_asof`; fail → file false, no `write_sync_complete` |
| `tests/test_sync_spec_e_passes.py` | update `write_sync_complete` spies → `*a, **k` |
| `tests/test_sync_from_universe.py` | same spy style |
| `tests/test_sync_budget.py` | `write_sync_complete` calls + file SoT asserts |
| `tests/test_live_shadow_sync_authority.py` (new) | skip-still-0; fill hard-fail; catch-up |
| `tests/test_live_shadow_gate.py` | **migrate** fill-path tests: plant fresh SoT or monkeypatch check→0 |
| `tests/test_paper_book.py` | regression: still green without SoT |
| docs (runbook only in this plan) | incomplete/stale tip note — Spec/todo final status in sister Task 2 |

```text
Task 0 (sync_status module + unit tests)
  └─► Task 1 (wire sync_bars_sample + migrate write_sync_complete callers/spies)
        └─► Task 2 (wire run_asof + migrate test_live_shadow_gate fill paths)
              └─► Task 3 (runbook only; Spec/todo deferred to sister)
```

---

### Task 0: `sync_status` helpers + unit tests

**Files:**
- Create: `scripts/common/sync_status.py`
- Create: `tests/test_sync_status.py`

**Interfaces:**
- Produces:
  - `DEFAULT_SYNC_STATUS_PATH` = `os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache", "sync_status.json")` (same pattern as `bars.DEFAULT_BARS_DB`)
  - `write_sync_status(*, sync_complete: bool, session_asof: str, elapsed_min: float = 0.0, path: str | Path | None = None, written_at: str | None = None) -> None`
  - `read_sync_status(path: str | Path | None = None) -> dict | None`
  - `check_sync_complete_for_fill(*, fill_asof: str, status_path: str | Path | None = None) -> int`  # 0 ok, 1 fail
  - Check FAIL if: missing/invalid JSON; `sync_complete is not True`; missing/null/non-str `session_asof`; `session_asof < fill_asof`
  - Honor `TRENDING_ALLOW_INCOMPLETE_FILL=1` → return 0 (dangerous; unit-test only)

- [ ] **Step 1: Failing tests** (`tmp_path` inject `path=` / `status_path=`):
  - write false → check(fill_asof=S) == 1
  - write true session D2 → check(D2)==0 and check(D1)==0 for D1<D2
  - true session D1, fill D2>D1 → 1
  - missing file → 1
  - invalid JSON → 1
  - `sync_complete=true` but missing/null `session_asof` → 1
  - env bypass set → 0 even if missing; default env does **not** bypass

- [ ] **Step 2: Implement** atomic JSON write + check predicate

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_sync_status.py -q
```

- [ ] **Step 4: Commit**

```bash
git add scripts/common/sync_status.py tests/test_sync_status.py
git commit -m "$(cat <<'EOF'
feat(sync): add sync_status SoT helpers and freshness check

EOF
)"
```

---

### Task 1: Wire `sync_bars_sample` + migrate `write_sync_complete` callers

**Files:**
- Modify: `scripts/sync_bars_sample.py`
- Modify: `tests/test_sync_hard_freeze_gate.py`
- Modify: `tests/test_sync_spec_e_passes.py`
- Modify: `tests/test_sync_from_universe.py`
- Modify: `tests/test_sync_budget.py`

**Interfaces:**
- `write_sync_complete(complete: bool, elapsed_min: float = 0.0, *, session_asof: str) -> None`  
  - keyword-only `session_asof`  
  - writes GITHUB_OUTPUT (existing) **and** `write_sync_status(sync_complete=complete, session_asof=session_asof, elapsed_min=elapsed_min)`
- `main` success end always passes `session_asof=session_asof.isoformat()`
- After `session_asof` / `conn` ready, **before** OHLC loop: `write_sync_status(False, session_asof=...)`
- `except` around `run_spec_e_passes`: `write_sync_status(False, ...)`; `return 1`; **never** `write_sync_complete`
- Empty-universe early `return 1`: leave pessimistic false file (already written); do not call `write_sync_complete`

**Spy migration (钉死):** every monkeypatch of `write_sync_complete` must accept `*args, **kwargs` (or explicit `session_asof=...`). Listed files above.

- [ ] **Step 1: Extend / update tests**
  - hard_freeze fail → status file false; spy shows `write_sync_complete` not called; no GITHUB_OUTPUT true
  - success incomplete → file `sync_complete=false` + `session_asof`; GITHUB_OUTPUT false if env set
  - success complete → file true
  - `test_github_output_sync_complete`: pass `session_asof=...`; assert GITHUB_OUTPUT **and** file contents
  - optional: `with_limits` not entered when `complete=false` (extend sync test or cite `if args.with_limits and complete` + new assert)

- [ ] **Step 2: Implement wiring + signature**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_sync_hard_freeze_gate.py tests/test_sync_status.py \
  tests/test_sync_budget.py tests/test_sync_spec_e_passes.py tests/test_sync_from_universe.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(sync): pessimistic sync_status writes on sync paths

EOF
)"
```

---

### Task 2: Wire `run_asof` + migrate existing live_shadow fill tests

**Files:**
- Modify: `scripts/eval/live_shadow_step.py`
- Create: `tests/test_live_shadow_sync_authority.py`
- Modify: `tests/test_live_shadow_gate.py` — **all fill-path tests** that reach `fill_day` / `insert_paper_fills`
- Run (no modify unless broken): `tests/test_paper_book.py`

**Interfaces:**
- Consumes: `check_sync_complete_for_fill(fill_asof=T, ...)`
- Placement: after `candidate_bars_ready` skip (return 0), **immediately before** `fill_day(...)`
- On check != 0: stderr per Spec; `conn.close()`; **return 1**

**Migrate `test_live_shadow_gate.py` (Critical):**  
For each test that reaches fill (including at least: `test_param_version_copied_from_confirm_day`, `test_second_asof_does_not_duplicate_consumed`, `test_from_heartbeat_walks_all_ok_days`, `test_catchup_day_without_limits_does_not_data_gap_consume`, `test_same_asof_pending_sell_does_not_fill_while_skipping_insert`):
- shared helper: write SoT with `sync_complete=true`, `session_asof` ≥ fill `T` via `tmp_path` + monkeypatch `DEFAULT_SYNC_STATUS_PATH` / `status_path`, **or**
- monkeypatch `check_sync_complete_for_fill` → 0  
**Forbidden:** setting `TRENDING_ALLOW_INCOMPLETE_FILL` for these CI tests.

Skip-path tests (`not_on_calendar`, `missing_bars`, meta-not-ok) must **not** require SoT and must still return 0.

- [ ] **Step 1: Failing / migration tests**
  - New file: missing SoT + would-fill → 1, no `insert_paper_fills`
  - calendar skip + missing SoT → 0
  - `missing_bars` + missing SoT → 0
  - SoT tip D2, fill D1 < D2 → can fill (0)
  - SoT tip D1, fill D2 > D1 → 1
  - direct `run_asof` gated
  - Update existing fill-path tests in `test_live_shadow_gate.py` as above

- [ ] **Step 2: Implement gate**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_live_shadow_sync_authority.py tests/test_live_shadow_gate.py \
  tests/test_paper_book.py tests/test_p2_workflow_order.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(shadow): hard-fail live_shadow without fresh sync_status

EOF
)"
```

---

### Task 3: Runbook only (Spec/todo deferred)

**Files:**
- Modify: `docs/ops/hard-freeze-stamp-runbook.md` — incomplete / stale tip → shadow blocked until full sync
- **Do not** mark Spec/todo 已落地 here if same-PR with limit_rule (sister Task 2 owns final wording)

- [ ] **Step 1: Runbook edit**

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs(ops): note sync_status gate for live_shadow

EOF
)"
```

---

## Self-review checklist

- [ ] Catch-up: tip ASOF authorizes T ≤ ASOF
- [ ] Stale tip: tip D1 rejects fill D2 > D1
- [ ] Missing `session_asof` FAILS check
- [ ] hard_freeze fail does not call `write_sync_complete`
- [ ] All listed spies accept `session_asof` / `**kwargs`
- [ ] `test_live_shadow_gate` fill paths plant SoT (no env bypass)
- [ ] 0-skips (calendar + missing_bars) remain exit 0 without SoT
- [ ] `paper_book` still green without SoT
- [ ] Spec/todo 已落地 deferred to sister Task 2

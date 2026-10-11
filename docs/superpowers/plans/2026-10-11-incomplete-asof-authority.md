# Incomplete × asof authority (sync_status + live_shadow gate) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `data/cache/sync_status.json` with pessimistic/fail-false writes; hard-fail `live_shadow_step.run_asof` when SoT is missing/incomplete/stale tip (`session_asof < fill_asof`), without breaking Spec F catch-up or Protocol B hard_freeze-fail semantics.

**Architecture:** New small module for SoT read/write + check; extend `sync_bars_sample` early/fail/success paths; gate in `run_asof` after 0-skips and immediately before `fill_day`.

**Tech Stack:** Python 3.11, pytest, JSON file SoT under `data/cache/` (gitignored).

## Global Constraints

- Spec: [`2026-10-11-incomplete-asof-authority-design.md`](../specs/2026-10-11-incomplete-asof-authority-design.md) (post re-review: `session_asof ≥ fill_asof`)
- Freshness: `sync_complete is true` **and** `session_asof >= fill_asof` (YYYY-MM-DD string order)
- Gate **only** `live_shadow_step.run_asof`; **not** `paper_book` / `daily_run`
- Gate **after** `not_on_calendar` / `live_allowed` / `missing_bars` return 0; **before** `fill_day`
- `write_sync_status` = file only; `write_sync_complete` = success-end GITHUB_OUTPUT **and** final file; hard_freeze fail → `write_sync_status(false)` only, **never** `write_sync_complete`
- Atomic file write: temp + `os.replace`
- Env bypass: only `TRENDING_ALLOW_INCOMPLETE_FILL=1`; CI main path must not rely on it
- Do not commit `data/cache/sync_status.json`; prefer `.venv/bin/pytest`
- Sister plan [`2026-10-11-limit-rule-rollback-guard.md`](2026-10-11-limit-rule-rollback-guard.md) wires **after** this gate

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/sync_status.py` (new) | path constant; `write_sync_status`; `read_sync_status`; `check_sync_complete_for_fill`; atomic write |
| `scripts/sync_bars_sample.py` | early pessimistic write; fail-path status; extend `write_sync_complete` |
| `scripts/eval/live_shadow_step.py` | call check before `fill_day` |
| `scripts/check_sync_complete.py` (optional CLI) | thin wrapper |
| `tests/test_sync_status.py` | SoT + freshness matrix |
| `tests/test_sync_hard_freeze_gate.py` | extend: fail writes false file, no `write_sync_complete` |
| `tests/test_live_shadow_gate.py` (or new `test_live_shadow_sync_authority.py`) | skip-still-0; fill path hard-fail; catch-up ok |
| docs / Spec status / todo | Done-when |

```text
Task 0 (sync_status module + unit tests)
  └─► Task 1 (wire sync_bars_sample write paths)
        └─► Task 2 (wire run_asof check)
              └─► Task 3 (docs + Spec status; todo partial until sister lands)
```

**Same-PR with limit_rule:** implement this plan first; sister plan Task wire assumes this check already runs.

---

### Task 0: `sync_status` helpers + unit tests

**Files:**
- Create: `scripts/common/sync_status.py`
- Create: `tests/test_sync_status.py`

**Interfaces:**
- Produces:
  - `DEFAULT_SYNC_STATUS_PATH` → repo-relative `data/cache/sync_status.json` (resolve from project root like other data paths)
  - `write_sync_status(*, sync_complete: bool, session_asof: str, elapsed_min: float = 0.0, path: str | Path | None = None, written_at: str | None = None) -> None`
  - `read_sync_status(path: str | Path | None = None) -> dict | None`
  - `check_sync_complete_for_fill(*, fill_asof: str, status_path: str | Path | None = None) -> int`  # 0 ok, 1 fail
  - Honor `TRENDING_ALLOW_INCOMPLETE_FILL=1` → return 0 (document dangerous)

- [ ] **Step 1: Failing tests** in `tests/test_sync_status.py`:
  - write false → check(fill_asof=S) == 1
  - write_complete true session D2 → check(D2)==0 and check(D1)==0 for D1<D2
  - true session D1, fill D2>D1 → 1
  - missing file → 1
  - invalid JSON → 1
  - env bypass set → 0 even if missing (and a test that default env does not bypass)

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

### Task 1: Wire `sync_bars_sample` write paths

**Files:**
- Modify: `scripts/sync_bars_sample.py`
- Modify: `tests/test_sync_hard_freeze_gate.py` (and/or `tests/test_sync_budget.py` if it asserts `write_sync_complete`)

**Interfaces:**
- Consumes: `write_sync_status`, and keep name `write_sync_complete` but extend signature with `session_asof: str`
- After `session_asof` / `conn` ready and **before** OHLC loop: `write_sync_status(False, session_asof=session_asof.isoformat(), ...)`
- `except` around `run_spec_e_passes`: `write_sync_status(False, ...)`; `return 1`; **do not** call `write_sync_complete`
- Success end: `write_sync_complete(complete, elapsed_min, session_asof=session_asof.isoformat())` which writes GITHUB_OUTPUT (existing) **and** `write_sync_status(complete, ...)`

- [ ] **Step 1: Extend / add tests**
  - hard_freeze fail → status file false; `write_sync_complete` not called (spy); no GITHUB_OUTPUT true
  - success incomplete → file `sync_complete=false`, `session_asof` set; GITHUB_OUTPUT false if env set
  - success complete → file true

- [ ] **Step 2: Implement wiring**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_sync_hard_freeze_gate.py tests/test_sync_status.py tests/test_sync_budget.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(sync): pessimistic sync_status writes on sync paths

EOF
)"
```

---

### Task 2: Wire `run_asof` gate

**Files:**
- Modify: `scripts/eval/live_shadow_step.py`
- Create or extend: `tests/test_live_shadow_sync_authority.py`

**Interfaces:**
- Consumes: `check_sync_complete_for_fill(fill_asof=T, ...)`
- Placement: after `candidate_bars_ready` skip (return 0), **immediately before** `fill_day(...)`
- On check != 0: print stderr per Spec; `conn.close()`; **return 1**
- Use `bars_path` only for bars load (unchanged); SoT path default

- [ ] **Step 1: Failing tests**
  - missing SoT + would-fill fixture → return 1, no `insert_paper_fills`
  - calendar skip with missing SoT → still 0
  - SoT true tip D2, fill D1 < D2 → can reach fill (mock fill ok / return 0)
  - SoT true tip D1, fill D2 > D1 → 1
  - direct `run_asof` (not via main) still gated

- [ ] **Step 2: Implement gate**

- [ ] **Step 3: Pytest**

```bash
.venv/bin/pytest tests/test_live_shadow_sync_authority.py tests/test_live_shadow_gate.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(shadow): hard-fail live_shadow without fresh sync_status

EOF
)"
```

---

### Task 3: Docs + Spec status (incomplete slice)

**Files:**
- Modify: Spec status → 已落地（或「code 已合；与 limit_rule 同 PR 时待姐妹」——若同 PR，defer final todo wording to sister Task docs）
- Modify: `docs/ops/hard-freeze-stamp-runbook.md` — one bullet: incomplete / stale tip → shadow blocked until full sync
- Optional: `scripts/check_sync_complete.py` CLI
- README product sentence if missing

- [ ] **Step 1: Docs edits**

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: mark incomplete-asof authority Spec landed

EOF
)"
```

---

## Self-review checklist

- [ ] Catch-up: tip ASOF authorizes T ≤ ASOF
- [ ] Stale tip: tip D1 rejects fill D2 > D1
- [ ] hard_freeze fail does not call `write_sync_complete`
- [ ] 0-skips remain exit 0 without SoT
- [ ] `paper_book` untouched

# Basket VOL_score (L2/L1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Spec C deferral: L2/L1 `VOL_score` from paired Σamount/Σfloat_mv on synth bars; digest「量」filled; enable L2 `danger` once amount series exists; bump to `p05-v5`.

**Architecture:** Extend `synthesize_basket_bars` with paired Σ fields; reuse `turnover_from_bar` / `compute_vol_scores`; cache `synth_by_code` for VOL + exit_tags; flip `enable_l2_danger=True` in `assign_exit_tags` wire.

**Tech Stack:** Python 3.11, SQLite, pytest. Depends on exit-tags plan landed (`exit_tags.py`, `tags` column, open flag).

## Global Constraints

- Spec: [`2026-10-11-basket-vol-score-design.md`](../specs/2026-10-11-basket-vol-score-design.md)
- Prerequisite: [`2026-10-11-exit-tags.md`](2026-10-11-exit-tags.md) merged (or same PR after exit-tags tasks)
- Paired Σ only: member enters **both** sums iff amount finite ∧ float_mv finite ∧ float_mv>0
- Do not change price chain / `normalize_weights` / RS
- Remove post-peer forced `VOL_score=None` for l2/l1; update `test_vol_score` constant-null asserts
- `param_version` end state **`p05-v5`** with `exit_tags_enabled: true`; Protocol B stamp refresh on final pv
- Prefer `.venv/bin/pytest`; no dirty `data/cache/*` commits

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/metrics/l2_synth.py` | paired Σ `amount` / `float_mv` on output bars |
| `scripts/metrics/vol_score.py` | optional `assign_vol_scores` helper (or keep inline DRY) |
| `scripts/daily_run.py` | synth cache; basket VOL; `enable_l2_danger=True` |
| `scripts/metrics/exit_tags.py` | honor `enable_l2_danger` for L2 amount spine |
| `scripts/issues/digest.py` | replace deferred VOL footnote |
| `config/metrics/a_share_daily.yaml` | `p05-v5` |
| `tests/test_l2_synth_vol.py` / `tests/test_vol_score.py` / `tests/test_exit_tags.py` | Σ pair, basket VOL, L2 danger |
| Spec C + todo + Spec status | Done-when |

```text
Task 0 (paired Σ on synthesize_basket_bars)
  └─► Task 1 (basket VOL wire + drop null force)
        └─► Task 2 (enable L2 danger)
              └─► Task 3 (digest footnote)
                    └─► Task 4 (p05-v5 + docs)
```

**Same-PR note (钉死):**  
1. Exit-tags Tasks **0–6** in order — Task 6 = **docs/todo/§11/Spec status only** (no `p05-v4` bump, no enable flip).  
2. This plan Tasks **0–3**.  
3. This Task **4** = sole yaml bump: `exit_tags_enabled: true` + `param_version: p05-v5` + CI asserts → `p05-v5`.  
Exit Spec §5 #5 same-PR exception applies.  
**Serial merges alternative:** exit Task 6 ships `p05-v4` + enable + asserts; then this Task 4 → `p05-v5` + asserts again.

---

### Task 0: Paired Σamount / Σfloat_mv on synth

**Files:**
- Modify: `scripts/metrics/l2_synth.py`
- Create: `tests/test_l2_synth_amount.py` (or extend existing l2 synth tests)

**Interfaces:**
- Each emitted bar may include `amount`, `float_mv` (float or absent/None)
- Membership = that day’s `r_members`; paired gate per Spec §3.1

- [ ] **Step 1: Failing tests**

```python
def test_paired_sum_skips_member_missing_amount_or_mv():
    # member A: amount+mv ok; member B: amount only; member C: mv only
    # Σ should equal A only for both fields
    ...

def test_no_paired_members_omits_or_nulls_amount_mv():
    ...

def test_price_path_unchanged_when_amounts_added():
    # same closes/high/low as before for a fixture that already had OHLC-only test
    ...
```

- [ ] **Step 2: Implement Σ in `synthesize_basket_bars`** after OHLC computed, before `out.append`

- [ ] **Step 3: Pytest + commit**

```bash
.venv/bin/pytest tests/test_l2_synth_amount.py tests/test_l2_synth.py -q
git add scripts/metrics/l2_synth.py tests/test_l2_synth_amount.py
git commit -m "$(cat <<'EOF'
feat(metrics): paired Σamount/Σfloat_mv on basket synth bars

EOF
)"
```

---

### Task 1: Basket `VOL_score` wire + shared synth cache

**Depends on:** Task 0; exit-tags Task 4 already introduced `l2_synth_by_code` for L2 (may be OHLC-only).

**Files:**
- Modify: `scripts/daily_run.py`
- Modify: `scripts/metrics/vol_score.py` (optional `assign_vol_scores`)
- Modify: `tests/test_vol_score.py` (replace always-null basket asserts)

**Interfaces:**
- Produces: asof L2/L1 `VOL_score` via same `compute_vol_scores` as stocks
- **Shared cache (钉死，禁二次 synthesize):**
  1. In existing L2 loop: `synth_by_code[code] = synth` (after Task 0, bars include paired Σ).
  2. In existing L1 loop: `synth_by_code[l1_id] = synth`.
  3. VOL assign reads **only** `synth_by_code` (no new `synthesize_basket_bars` call).
  4. `assign_exit_tags(..., l2_synth_by_code={k: synth_by_code[k] for k in l2_codes}, enable_l2_danger=...)` — pass the **L2 subset** under the exit-tags kwarg name (do not rename the exit-tags API in this task unless both call sites update together).
- Remove post-peer force-null loop:
  ```python
  for r in l2_rows: r["VOL_score"] = None
  for r in l1_rows: r["VOL_score"] = None
  ```
- Keep `_basket_asof_row` default None as placeholder OK if overwritten

- [ ] **Step 1: Failing tests**

```python
def test_basket_vol_null_below_min_samples():
    ...

def test_basket_vol_matches_compute_vol_scores_on_synth_turnovers():
    ...

def test_assign_vol_does_not_change_rs():
    ...
```

Delete/replace `test_basket_vol_score_always_null_after_wire`.

- [ ] **Step 2: Implement** — fill `synth_by_code` in L2/L1 loops; VOL from cache; pass L2 subset into `assign_exit_tags` as `l2_synth_by_code`; optionally unify stock path through `assign_vol_scores(...)`.

- [ ] **Step 3: Pytest + commit**

```bash
.venv/bin/pytest tests/test_vol_score.py tests/test_l2_daily_run_wire.py tests/test_l1_daily_run_wire.py -q
git add scripts/daily_run.py scripts/metrics/vol_score.py tests/test_vol_score.py
git commit -m "$(cat <<'EOF'
feat(metrics): L2/L1 VOL_score from synth turnover spine

EOF
)"
```

---

### Task 2: Enable L2 `danger`

**Depends on:** Task 0–1; exit-tags `assign_exit_tags(..., enable_l2_danger=False)`.

**Files:**
- Modify: `scripts/metrics/exit_tags.py` (L2 danger when flag True and synth has amount points)
- Modify: `scripts/daily_run.py` (`enable_l2_danger=True`)
- Modify: `tests/test_exit_tags.py`

**Interfaces:**
- When `enable_l2_danger=True`, L2 uses synth spine amounts + closes for same danger rule as stocks
- L1 still `[]`

- [ ] **Step 1: Failing golden** — L2 synth with extreme down-day + high amount vs own history → `danger` in tags when enabled; disabled → absent.

- [ ] **Step 2: Implement + wire True**

- [ ] **Step 3: Pytest + commit**

```bash
.venv/bin/pytest tests/test_exit_tags.py -q
git add scripts/metrics/exit_tags.py scripts/daily_run.py tests/test_exit_tags.py
git commit -m "$(cat <<'EOF'
feat(metrics): enable L2 danger exit tag when synth amount exists

EOF
)"
```

---

### Task 3: Digest footnote +「量」

**Depends on:** Task 1.

**Files:**
- Modify: `scripts/issues/digest.py`
- Modify: `tests/test_digest_rs_vol.py` (and any footnote asserts)

**Interfaces:** none

- [ ] **Step 1: Failing test** — rendered markdown must **not** contain  
  `L2/L1「量」本 slice 为空——篮子 VOL 后放`  
  and should contain neutral `量=VOL_score（篮换手自身分位` (or Spec exact sentence); L2 row with VOL_score=80 shows `80` in「量」.

- [ ] **Step 2: Edit footnote + ensure VOL cell formatting**

- [ ] **Step 3: Pytest + commit**

```bash
.venv/bin/pytest tests/test_digest_rs_vol.py tests/test_digest_exit_tags.py -q
git add scripts/issues/digest.py tests/test_digest_rs_vol.py
git commit -m "$(cat <<'EOF'
fix(digest): show basket VOL_score; drop deferred-volume footnote

EOF
)"
```

---

### Task 4: `p05-v5` + docs

**Depends on:** Tasks 0–3.

**Files:**
- Modify: `config/metrics/a_share_daily.yaml` → `param_version: p05-v5` (keep / set `exit_tags_enabled: true`)
- Modify: production-yaml CI asserts → `p05-v5`:
  - `tests/test_features.py`
  - `tests/test_hard_freeze_config.py`
  - `tests/test_daily_run_metrics_wire.py`
  - Grep `tests/` for leftover `p05-v4` / `p05-v3` against real yaml
- Modify: `todo.md` P1 篮子 VOL
- Modify: `docs/superpowers/specs/2026-10-07-rs-c1-vol-design.md` §2.3 / 后放 list → point to this Spec
- Modify: `docs/superpowers/specs/2026-10-11-basket-vol-score-design.md` status → 已落地

- [ ] **Step 1: Bump yaml** (+ enable flag if same-PR deferred from exit Task 6)

- [ ] **Step 2: Update CI version asserts to `p05-v5`**

- [ ] **Step 3: Spec C + todo + status**

- [ ] **Step 4: Pytest smoke + commit**

```bash
.venv/bin/pytest tests/test_vol_score.py tests/test_exit_tags.py tests/test_l2_synth_amount.py \
  tests/test_digest_rs_vol.py tests/test_features.py tests/test_hard_freeze_config.py \
  tests/test_daily_run_metrics_wire.py -q
git add config/metrics/a_share_daily.yaml tests/test_features.py tests/test_hard_freeze_config.py \
  tests/test_daily_run_metrics_wire.py todo.md docs/superpowers/specs/
git commit -m "$(cat <<'EOF'
chore(metrics): bump param_version to p05-v5 after basket VOL

EOF
)"
```

- [ ] **Step 5: Ops** — PR body: sync hard_freeze+stamp for `p05-v5` before metrics (Protocol B).

---

## Done-when checklist

- [ ] Spec §5 验收 1–9
- [ ] Spec C §2.3 basket-null language superseded in docs
- [ ] Exit-tags L2 danger only when this plan’s wire sets `enable_l2_danger=True`
- [ ] RS unchanged by VOL assign (test)

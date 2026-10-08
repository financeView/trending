# Spec D: Universe Expansion (YAML daily refresh + unmapped visibility) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cron-refresh `stock_sw_l2.yaml` before sync (commit+push on guarded diff), expose real `unmapped_count` + IPO≥3 alerts as soft warns, without tree-out bars warmup.

**Architecture:** Approach 1 — same `daily-trend` job: unit tests → `refresh_taxonomy` (always exit 0) → sync mapped bars → `daily_run`. Git remains canonical; fetch/guard/push failures keep HEAD YAML and continue the day. Unmapped/IPO computed in the taxonomy step (and reused by `daily_run`) so deferred sync still advances the IPO clock and can commit `heartbeat.taxonomy`.

**Tech Stack:** Python 3.11, PyYAML, existing `akshare` / Eastmoney clist helpers, pytest, GitHub Actions (`contents: write` already present).

## Global Constraints

- Spec: [`2026-10-08-universe-expansion-design.md`](../specs/2026-10-08-universe-expansion-design.md) (self-review + indep-CR + final-review patches)
- **No** tree-out `sync_bars` warmup; sync list stays `load_universe_codes()`
- Taxonomy step / CLI **always exit 0**; status via `GITHUB_OUTPUT` + logs — **no** `continue-on-error` for expected fail
- Guard: candidate `|mapped| ≥ 0.80 × HEAD`; `|adds|+|deletes|+|sw_l2_changes| ≤ 80`
- `map_version` bump only on `ts↔sw_l2` change; three headers stay equal; header-only edits for `sw_l2_to_l1` / `l1_buckets`
- first_seen path: **`data/unmapped_first_seen.json`** (never under `data/cache/`)
- IPO list date: Eastmoney clist **`f26`**; fallback first_seen; clock vs `session_asof` inclusive
- Soft gate: never flip `evaluate_ok` to partial for unmapped/IPO/clist fail
- `unmapped_count` / IPO fields written to **`session_asof` `run_meta` only**
- Warn text **appended** to Spec A `decision.reason` with `"; "`
- Forbid `git push --force`; taxonomy step sets its own `user.name` / `user.email`
- Out of slice: Spec E, engine_state, BJ-in-tree, PR-gated publish, volume/RS changes
- Do not commit dirty `data/cache/trade_dates.json` in feat commits unless intentionally updating first_seen/heartbeat as specified

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/taxonomy/membership.py` | Semantic membership load/compare; bump; guards; header patch |
| `scripts/taxonomy/unmapped.py` | clist set, `unmapped_count`, IPO alert, first_seen, `f26` parse |
| `scripts/taxonomy/refresh_taxonomy.py` | Orchestration CLI: fetch → patch names → guard → write → git → heartbeat |
| `scripts/taxonomy/fetch_sw_members.py` | Keep normalize; extend `dump_yaml` for `name_zh` + explicit `map_version` |
| `scripts/taxonomy/patch_stock_names.py` | Reuse `rewrite_yaml` / name map (may export helpers) |
| `scripts/daily_run.py` | asof `unmapped_count`; `git_sha`; warn append; preserve `heartbeat.taxonomy` |
| `scripts/common/db.py` | Only if heartbeat helper needs a tiny merge API (prefer reuse) |
| `.github/workflows/daily-trend.yml` | Insert taxonomy step after unit tests, before sync |
| `data/unmapped_first_seen.json` | Check-in `{}` initially |
| `tests/test_universe_yaml_map.py` | Unpin `sw2021-v1` |
| `tests/test_taxonomy_membership.py` | Diff / bump / guard / header patch |
| `tests/test_unmapped_metrics.py` | Formula / f26 / first_seen / IPO≥3 |
| `tests/test_refresh_taxonomy.py` | Mocked fetch fail / guard fail / exit 0 |
| `tests/test_daily_run_unmapped.py` | run_meta + warn append + git_sha (light) |
| `todo.md` / `README.md` | Done-when |

```text
Task 0 (unpin map_version test + first_seen stub)
  └─► Task 1 (membership diff / bump / guard / header patch)
        └─► Task 2 (dump_yaml + name merge + refresh_taxonomy core)
              └─► Task 3 (unmapped / IPO / f26 / first_seen)
                    ├─► Task 4 (daily_run wire) ──┐
                    └─► Task 5 (workflow) ─────────┴─► Task 6 (done-when docs)
```

Task 4 and Task 5 may run in parallel after Task 3. Task 6 waits for both.

---

### Task 0: Unpin `sw2021-v1` + first_seen stub

**Files:**
- Modify: `tests/test_universe_yaml_map.py`
- Create: `data/unmapped_first_seen.json` with `{}`
- Modify: Spec status line to 「plan 就绪」 if still 「设计稿」 — optional in this commit

**Interfaces:** none

- [ ] **Step 1: Failing expectation (document current pin)**

Run: `.venv/bin/pytest tests/test_universe_yaml_map.py::test_every_section4_code_once_and_14_l1 -q`  
Expected: PASS today (still pinned). Then edit the assert.

- [ ] **Step 2: Replace pin with three-header consistency**

In `tests/test_universe_yaml_map.py`, replace:

```python
    meta = yaml.safe_load(L2_YAML.read_text(encoding="utf-8"))
    assert meta["map_version"] == "sw2021-v1"
```

with:

```python
    import re

    def _header_version(path: Path) -> str:
        meta = yaml.safe_load(path.read_text(encoding="utf-8"))
        v = meta["map_version"]
        assert re.fullmatch(r"sw2021-v\d+", str(v)), v
        return str(v)

    v_l2 = _header_version(L2_YAML)
    v_l1 = _header_version(L1_YAML)
    v_stock = _header_version(ROOT / "config" / "taxonomy" / "stock_sw_l2.yaml")
    assert v_l2 == v_l1 == v_stock
```

- [ ] **Step 3: Add empty first_seen file**

```bash
printf '{}\n' > data/unmapped_first_seen.json
```

Ensure it is **not** gitignored (path is `data/unmapped_first_seen.json`, not under `data/cache/`).

- [ ] **Step 4: Pytest**

Run: `.venv/bin/pytest tests/test_universe_yaml_map.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_universe_yaml_map.py data/unmapped_first_seen.json
git commit -m "$(cat <<'EOF'
test(taxonomy): allow sw2021-vN header consistency for Spec D bumps

EOF
)"
```

---

### Task 1: Membership diff, bump, guard, header patch

**Files:**
- Create: `scripts/taxonomy/membership.py`
- Test: `tests/test_taxonomy_membership.py`

**Interfaces:**
- Produces:
  - `Member = TypedDict` with `ts_code: str`, `sw_l2_code: Optional[str]`, `name_zh: Optional[str]`
  - `load_members_from_yaml(path: str) -> tuple[str, list[Member]]`  # version, sorted members
  - `semantic_equal(a: list[Member], b: list[Member]) -> bool`
  - `membership_delta(head: list[Member], cand: list[Member]) -> tuple[int,int,int]`  # adds, deletes, sw_l2_changes
  - `guard_ok(head_mapped_n: int, cand_mapped_n: int, adds: int, deletes: int, changes: int, *, min_frac: float = 0.8, max_delta: int = 80) -> bool`
  - `bump_map_version(current: str) -> str`  # `sw2021-vN` → `vN+1`; raises `ValueError` on bad parse
  - `patch_map_version_header(path: str, new_version: str) -> None`  # first `map_version:` line only
  - `mapped_count(members: list[Member], allowed: set[str]) -> int`

- [ ] **Step 1: Failing tests**

Create `tests/test_taxonomy_membership.py`:

```python
from scripts.taxonomy.membership import (
    bump_map_version,
    guard_ok,
    membership_delta,
    semantic_equal,
)


def test_bump_map_version():
    assert bump_map_version("sw2021-v1") == "sw2021-v2"
    assert bump_map_version("sw2021-v12") == "sw2021-v13"


def test_bump_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        bump_map_version("p05-v1")


def test_membership_delta_and_guard():
    head = [
        {"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "A"},
        {"ts_code": "000002.SZ", "sw_l2_code": "370100", "name_zh": None},
    ]
    cand = [
        {"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "A"},
        {"ts_code": "000003.SZ", "sw_l2_code": "480300", "name_zh": "C"},
    ]
    adds, deletes, changes = membership_delta(head, cand)
    assert (adds, deletes, changes) == (1, 1, 0)
    assert guard_ok(5508, 5508, 10, 0, 0) is True
    assert guard_ok(5508, 4000, 0, 0, 0) is False  # < 0.8
    assert guard_ok(5508, 5508, 50, 40, 0) is False  # 90 > 80


def test_name_only_semantically_differs_but_no_sw_change():
    a = [{"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "旧"}]
    b = [{"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": "新"}]
    assert semantic_equal(a, b) is False
    assert membership_delta(a, b) == (0, 0, 0)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_taxonomy_membership.py -q`  
Expected: FAIL import or missing functions

- [ ] **Step 3: Implement `scripts/taxonomy/membership.py`**

Minimal implementation matching interfaces above. `patch_map_version_header`: read text, replace only the first line matching `^map_version:\s*.*$` with `map_version: {new_version}`; do not yaml.dump the whole file. `membership_delta`: index by `ts_code`; add = in cand not head; delete = in head not cand; change = same ts, different normalized `sw_l2_code` (`None`/empty equal).

- [ ] **Step 4: Pytest PASS**

Run: `.venv/bin/pytest tests/test_taxonomy_membership.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/taxonomy/membership.py tests/test_taxonomy_membership.py
git commit -m "$(cat <<'EOF'
feat(taxonomy): membership diff, map_version bump, and refresh guards

EOF
)"
```

---

### Task 2: YAML writers + `refresh_taxonomy` orchestration (mocked I/O)

**Files:**
- Modify: `scripts/taxonomy/fetch_sw_members.py` (`dump_yaml`)
- Create: `scripts/taxonomy/refresh_taxonomy.py`
- Test: `tests/test_refresh_taxonomy.py`

**Interfaces:**
- Consumes: Task 1 membership helpers; `fetch_sw_members.normalize_member` / `fetch_latest_rows`; `patch_stock_names.rewrite_yaml` + `_name_map` (or inject)
- Produces:
  - `dump_yaml(rows, *, map_version: str, prior_names: dict[str,str] | None = None) -> str` — preserves `name_zh` from `prior_names` when present; never defaults version to wiping a newer header
  - `refresh_taxonomy_once(*, fetch_rows, name_map, repo_root, git: bool = False) -> dict` status keys: `taxonomy_fetch`, `map_version`, `taxonomy_commit`, counts…
  - CLI `main` always `return 0`; write `taxonomy_fetch=...` to `$GITHUB_OUTPUT` if set

- [ ] **Step 1: Failing tests for dump + refresh fail path**

```python
def test_dump_yaml_keeps_name_zh_and_version():
    from scripts.taxonomy.fetch_sw_members import dump_yaml
    text = dump_yaml(
        [{"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": ""}],
        map_version="sw2021-v3",
        prior_names={"000001.SZ": "平安银行"},
    )
    assert "map_version: sw2021-v3" in text
    assert "name_zh: 平安银行" in text


def test_refresh_vendor_fail_keeps_yaml(tmp_path, monkeypatch):
    # copy tiny HEAD yaml into tmp_path/config/taxonomy/...
    # monkeypatch fetch to raise
    # call refresh_taxonomy_once(git=False)
    # assert file bytes unchanged; status taxonomy_fetch == "fail"; return code path exit 0
```

(Implement the tmp_path fixture fully in the test file — copy minimal valid YAML with one mapped member.)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement dump_yaml signature change + refresh_taxonomy_once**

Logic order per spec §2.1 steps a–f (without real git when `git=False`):
1. Try fetch → on exception/empty mapped after normalize → status fail, no write
2. Build candidate members; merge prior `name_zh` from HEAD file; optional name_map overlay (failures leave prior names)
3. `guard_ok` → fail keeps HEAD
4. If semantic equal → `skipped_no_diff`
5. Else write `stock_sw_l2.yaml`; if membership/sw_l2 delta non-zero → `bump_map_version` + `patch_map_version_header` on three files; else keep version
6. Return status dict

Git (`git=True`): only in CLI when env `TAXONOMY_GIT=1` or `--git`; steps: config user, add paths, commit, pull --rebase --autostash, on conflict abort + restore HEAD files + `push_fail`, else push no-force.

- [ ] **Step 4: Pytest focused**

Run: `.venv/bin/pytest tests/test_refresh_taxonomy.py tests/test_fetch_sw_normalize.py -q`  
Expected: PASS (update any dump_yaml callers/tests if arity broke)

- [ ] **Step 5: Commit**

```bash
git add scripts/taxonomy/fetch_sw_members.py scripts/taxonomy/refresh_taxonomy.py tests/test_refresh_taxonomy.py
git commit -m "$(cat <<'EOF'
feat(taxonomy): refresh orchestration with guards and safe YAML dump

EOF
)"
```

---

### Task 3: Unmapped count + IPO (`f26`) + first_seen

**Files:**
- Create: `scripts/taxonomy/unmapped.py`
- Test: `tests/test_unmapped_metrics.py`
- Modify: `scripts/taxonomy/refresh_taxonomy.py` to call unmapped helper in step f

**Interfaces:**
- Consumes: `load_universe_codes`, `load_quarantine_codes`, `fetch_clist_all_a`, calendar `trading_days_inclusive` / `trade_dates`
- Produces:
  - `parse_em_list_date(f26_val) -> date | None`
  - `compute_unmapped_metrics(*, clist_rows or fetch, session_asof: date, first_seen_path: str) -> UnmappedMetrics` dataclass:
    - `unmapped_count: int | None`
    - `ipo_unmapped_alert_count: int | None`
    - `yaml_quarantine_size: int`
    - `clist_fetch: str`  # ok|fail
    - updates first_seen file for codes newly seen
  - Listing age: inclusive trading days from `list_date` or `first_asof` through `session_asof`

- [ ] **Step 1: Failing tests**

```python
from datetime import date
from scripts.taxonomy.unmapped import parse_em_list_date, compute_unmapped_metrics


def test_parse_f26_yyyymmdd_and_ms():
    assert parse_em_list_date("20240105") == date(2024, 1, 5)
    # 2024-01-05 00:00 UTC+8 ≈ pick a known ms fixture after implementing


def test_unmapped_count_formula(tmp_path, monkeypatch):
    # mapped = {000001.SZ}; clist = {000001.SZ, 000002.SZ} → count 1
    ...


def test_ipo_alert_first_seen(tmp_path, monkeypatch):
    # first_asof=2024-01-02, session_asof three trading days later → alert
    ...


def test_clist_fail_returns_null_counts(monkeypatch):
    # fetch raises → unmapped_count is None, clist_fetch == "fail"
    ...
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `unmapped.py`**

`fetch_clist_all_a(["f12","f13","f14","f26"])` for production path; tests inject rows. Never write `0` on failure.

- [ ] **Step 4: Wire into `refresh_taxonomy_once` step f** — write `heartbeat.taxonomy` via merge helper; when `git=True` and heartbeat/first_seen changed, commit those paths (even if YAML skipped).

Heartbeat shape:

```python
{
  "taxonomy_fetch": "...",
  "clist_fetch": "ok|fail",
  "unmapped_count": 123,  # or null
  "ipo_unmapped_alert_count": 0,
  "yaml_quarantine_size": 67,
  "map_version": "sw2021-v1",
  "taxonomy_commit": "abc" | "unpushed" | "",
}
```

Use a small helper that loads JSON, sets `data["taxonomy"]=...`, sets `updated_at`, writes — do **not** go through `write_heartbeat` if it forces `last_success` semantics awkwardly; either call `write_heartbeat({"job":"taxonomy", "status":"ok", ...fields})` after popping status, or dedicated `merge_heartbeat_key("taxonomy", fields)`.

- [ ] **Step 5: Pytest + commit**

```bash
git add scripts/taxonomy/unmapped.py scripts/taxonomy/refresh_taxonomy.py tests/test_unmapped_metrics.py
git commit -m "$(cat <<'EOF'
feat(taxonomy): unmapped_count and IPO alert metrics with f26

EOF
)"
```

---

### Task 4: `daily_run` wire

**Files:**
- Modify: `scripts/daily_run.py`
- Test: `tests/test_daily_run_unmapped.py` (new) and/or extend `tests/test_daily_run_metrics_wire.py`

**Interfaces:**
- Consumes: `compute_unmapped_metrics` (or cached result from env — prefer call helper once per `main()` for `session_asof`)
- Produces: `run_meta.unmapped_count` on **asof row only**; other days keep previous DB value (do not overwrite with today's clist). Append taxonomy warn to `warn` when asof.

- [ ] **Step 1: Failing tests**

```python
def test_asof_run_meta_unmapped_not_literal_zero(tmp_path, monkeypatch):
    # stub compute_unmapped_metrics → count 3
    # process_day or main one day
    # SELECT unmapped_count == 3


def test_warn_appends_ipo_alert(monkeypatch):
    # decision.reason limit warn + ipo → "limit...; taxonomy: ipo_unmapped_alert=1"


def test_git_sha_uses_head_when_env_set(monkeypatch):
    monkeypatch.setenv("TREND_GIT_SHA", "deadbeef")
    # or patch rev-parse; assert run_meta.git_sha
```

Implementation note for git_sha: prefer `os.environ.get("TAXONOMY_HEAD_SHA")` set by refresh CLI on successful push, else `subprocess` `git rev-parse HEAD`, else `GITHUB_SHA`.

- [ ] **Step 2: Implement**

In `process_day` / `main`:
- Remove `unmapped_count: 0` literal
- For `D == session_asof`: write metrics counts (NULL → Python `None` → SQL NULL)
- For `D != session_asof`: omit updating unmapped fields — use upsert that leaves column unchanged **or** re-read prior row; simplest: pass `unmapped_count` only when `D == session_asof`, and change upsert to not include key when absent (if upsert always writes all COLS, then SELECT previous value before write for non-asof days)

Check `upsert_rows` behavior — if it always replaces full row dict, for non-asof days copy existing `unmapped_count` from DB when present.

Warn append only on asof when `taxonomy_fetch` in (`fail`,`push_fail`) or `ipo_unmapped_alert_count>0` or `clist_fetch==fail`.

Preserve heartbeat: after `write_heartbeat(job=daily_run)`, assert taxonomy key remains (existing db.py keeps dict siblings — add test).

- [ ] **Step 3: Pytest + commit**

```bash
git add scripts/daily_run.py tests/test_daily_run_unmapped.py
git commit -m "$(cat <<'EOF'
feat(daily_run): real unmapped_count, taxonomy warn append, git_sha

EOF
)"
```

---

### Task 5: GitHub Actions workflow

**Files:**
- Modify: `.github/workflows/daily-trend.yml`

**Interfaces:** none (YAML)

- [ ] **Step 1: Insert taxonomy step after Unit tests, before Sync**

```yaml
      - name: Refresh taxonomy YAML
        id: taxonomy
        continue-on-error: false
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          python scripts/taxonomy/refresh_taxonomy.py --git
          # script always exits 0; exports taxonomy_fetch via GITHUB_OUTPUT
```

Ensure script documents writing:

```python
# if os.environ.get("GITHUB_OUTPUT"): append taxonomy_fetch=...
```

Do **not** add `continue-on-error: true`. Do **not** gate sync on taxonomy success (sync always runs next).

- [ ] **Step 2: Local sanity**

Run: `python scripts/taxonomy/refresh_taxonomy.py --help`  
Expected: shows `--git` flag

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily-trend.yml scripts/taxonomy/refresh_taxonomy.py
git commit -m "$(cat <<'EOF'
ci: run taxonomy refresh before mapped-universe sync

EOF
)"
```

---

### Task 6: Done-when docs

**Files:**
- Modify: `todo.md`, `README.md`
- Modify: `docs/superpowers/specs/2026-10-08-universe-expansion-design.md` status → **已落地** + plan link

- [ ] **Step 1: Update todo**

- Spec D row → completed with links; note YAML 日拉 + 计数/IPO 告警  
- §2.3 keep one leftover line: 树外 bars 预热仍后放  
- Landing blurb Next = Spec E  
- Header date optional

- [ ] **Step 2: Update README Still out**

Replace `unmapped 全A sync (Spec D)` with wording like: `tree-out bars warmup (deferred)`; keep E-related items if listed.

- [ ] **Step 3: Full suite**

Run: `.venv/bin/pytest tests/ -q`  
Expected: all green

- [ ] **Step 4: Commit**

```bash
git add todo.md README.md docs/superpowers/specs/2026-10-08-universe-expansion-design.md
git commit -m "$(cat <<'EOF'
docs: mark Spec D universe expansion ready for ship

EOF
)"
```

---

## Spec coverage checklist (self-review)

| Spec requirement | Task |
|------------------|------|
| tests → taxonomy → sync order | T5 |
| fetch + name patch soft | T2 |
| semantic diff / bump / three headers | T1–T2 |
| guard 0.8 / ≤80 | T1–T2 |
| exit 0 + GITHUB_OUTPUT | T2 / T5 |
| push / rebase abort / no force | T2 |
| first_seen path outside cache | T0 / T3 |
| unmapped formula + clist null | T3 |
| IPO f26 + ≥3 inclusive | T3 |
| heartbeat.taxonomy commit in taxonomy step | T2–T3 |
| daily_run asof-only counts + warn append + git_sha | T4 |
| unpin sw2021-v1 | T0 |
| no tree-out bars | Global / T5 (sync unchanged) |
| todo leftover warmup + Next E | T6 |

## Out of slice

Tree-out bars warmup, Spec E, engine_state, BJ quarantine rows, PR-gated publish, hard unmapped partial, SW annual >80 auto-apply.

---

## Plan self-review notes

1. **Coverage:** All final-review spec bullets map to T0–T6.  
2. **Placeholders:** None intentional; EM `f26` parse cases must be implemented with real sample values in T3 tests (engineer captures one ms example from docs or a fixture literal).  
3. **Types:** `UnmappedMetrics` and membership helpers named consistently across T1–T4.

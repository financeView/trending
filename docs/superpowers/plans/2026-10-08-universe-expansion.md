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
| `tests/test_refresh_taxonomy.py` | fetch fail / guard fail / name-only / bump / CLI exit 0 + GITHUB_OUTPUT |
| `tests/test_daily_run_unmapped.py` | run_meta + warn append + git_sha + soft-gate (evaluate_ok) |
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

- [ ] **Step 1: Replace pin with three-header consistency**

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

- [ ] **Step 2: Add empty first_seen file**

```bash
printf '{}\n' > data/unmapped_first_seen.json
```

Ensure it is **not** gitignored (path is `data/unmapped_first_seen.json`, not under `data/cache/`).

- [ ] **Step 3: Pytest**

Run: `.venv/bin/pytest tests/test_universe_yaml_map.py -q`  
Expected: PASS

- [ ] **Step 4: Commit**

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


def test_mapped_count_skips_null_sw_l2():
    from scripts.taxonomy.membership import mapped_count

    members = [
        {"ts_code": "000001.SZ", "sw_l2_code": "370100", "name_zh": None},
        {"ts_code": "000002.SZ", "sw_l2_code": None, "name_zh": None},
    ]
    assert mapped_count(members, {"370100"}) == 1


def test_patch_map_version_header_only_first_line(tmp_path):
    from scripts.taxonomy.membership import patch_map_version_header

    p = tmp_path / "sw_l2_to_l1.yaml"
    p.write_text(
        "map_version: sw2021-v1\n"
        "l2:\n"
        "  - {code: '370100', l1_id: l1_a, name_zh: x}\n",
        encoding="utf-8",
    )
    patch_map_version_header(str(p), "sw2021-v2")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("map_version: sw2021-v2\n")
    assert "370100" in text and "l1_a" in text
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
- Consumes: Task 1 membership helpers; `fetch_sw_members.normalize_member` / `fetch_latest_rows`; `patch_stock_names.rewrite_yaml` + `_name_map` (or inject); `scripts.common.calendar.latest_trade_day`
- Produces:
  - `dump_yaml(rows, *, map_version: str, prior_names: dict[str,str] | None = None) -> str` — preserves `name_zh` from `prior_names` when present; never defaults version to wiping a newer header
  - `refresh_taxonomy_once(*, fetch_rows, name_map, repo_root, session_asof: date, git: bool = False) -> dict` status keys: `taxonomy_fetch`, `map_version`, `taxonomy_commit`, counts…
    - **`session_asof` required** (CLI default: `latest_trade_day()`). first_seen values written in step f are always this asof — never queue `D` / wall-clock “today”.
  - CLI `main` always `return 0`; write `taxonomy_fetch=...` and `taxonomy_head_sha=...` (empty unless YAML push succeeded) to `$GITHUB_OUTPUT` if set

- [ ] **Step 1: Failing tests for dump + refresh fail path**

**Must-fix:** `dump_yaml` keeps backward-compatible defaults so `tests/test_fetch_sw_normalize.py` (`dump_yaml(rows)` with no kwargs) still passes — e.g. `map_version: str = "sw2021-v1"`, `prior_names: Optional[dict] = None`.

```python
from datetime import date
from pathlib import Path

from scripts.taxonomy.fetch_sw_members import dump_yaml
from scripts.taxonomy.refresh_taxonomy import refresh_taxonomy_once


def test_dump_yaml_keeps_name_zh_and_version():
    text = dump_yaml(
        [{"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": ""}],
        map_version="sw2021-v3",
        prior_names={"000001.SZ": "平安银行"},
    )
    assert "map_version: sw2021-v3" in text
    assert "name_zh: 平安银行" in text


def test_dump_yaml_positional_still_works_for_normalize_tests():
    text = dump_yaml(
        [{"ts_code": "000001.SZ", "industry_code": "801780", "industry_name": "银行"}]
    )
    assert "801780" not in text
    assert "sw_l2_code: null" in text


def _seed_taxonomy_tree(root: Path) -> None:
    tax = root / "config" / "taxonomy"
    tax.mkdir(parents=True)
    (tax / "stock_sw_l2.yaml").write_text(
        "map_version: sw2021-v1\n"
        "members:\n"
        "  - {ts_code: 000001.SZ, sw_l2_code: '370100', name_zh: 旧名}\n",
        encoding="utf-8",
    )
    (tax / "sw_l2_to_l1.yaml").write_text(
        "map_version: sw2021-v1\nl2:\n  - {code: '370100', l1_id: l1_a}\n",
        encoding="utf-8",
    )
    (tax / "l1_buckets.yaml").write_text(
        "map_version: sw2021-v1\nl1:\n  - {l1_id: l1_a}\n",
        encoding="utf-8",
    )


def test_refresh_vendor_fail_keeps_yaml(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    stock = tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml"
    before = stock.read_bytes()

    def _boom():
        raise RuntimeError("vendor down")

    st = refresh_taxonomy_once(
        fetch_rows=_boom,
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
    )
    assert st["taxonomy_fetch"] == "fail"
    assert stock.read_bytes() == before


def test_refresh_guard_fail_keeps_yaml(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    stock = tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml"
    before = stock.read_bytes()

    # candidate empties mapped → fails 0.80× guard
    st = refresh_taxonomy_once(
        fetch_rows=lambda: [],
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
    )
    assert st["taxonomy_fetch"] == "fail"
    assert stock.read_bytes() == before


def test_refresh_name_only_writes_no_bump(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    rows = [{"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"}]
    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=lambda: {"000001.SZ": "新名"},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
    )
    assert st["taxonomy_fetch"] == "ok"
    assert st["map_version"] == "sw2021-v1"
    text = (tmp_path / "config" / "taxonomy" / "stock_sw_l2.yaml").read_text(encoding="utf-8")
    assert "name_zh: 新名" in text


def test_refresh_membership_bump_three_headers(tmp_path):
    _seed_taxonomy_tree(tmp_path)
    rows = [
        {"ts_code": "000001.SZ", "industry_code": "370100", "industry_name": "银行"},
        {"ts_code": "000002.SZ", "industry_code": "370100", "industry_name": "万科"},
    ]
    st = refresh_taxonomy_once(
        fetch_rows=lambda: rows,
        name_map=lambda: {},
        repo_root=str(tmp_path),
        session_asof=date(2024, 1, 10),
        git=False,
    )
    assert st["taxonomy_fetch"] == "ok"
    assert st["map_version"] == "sw2021-v2"
    for name in ("stock_sw_l2.yaml", "sw_l2_to_l1.yaml", "l1_buckets.yaml"):
        assert "map_version: sw2021-v2" in (
            tmp_path / "config" / "taxonomy" / name
        ).read_text(encoding="utf-8")


def test_cli_fetch_fail_exit_zero_writes_github_output(tmp_path, monkeypatch):
    from scripts.taxonomy import refresh_taxonomy as rt

    _seed_taxonomy_tree(tmp_path)
    out = tmp_path / "gh_out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rt, "fetch_latest_rows", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert rt.main(["--no-git"]) == 0  # or argv default without --git
    body = out.read_text(encoding="utf-8")
    assert "taxonomy_fetch=fail" in body
    assert "taxonomy_head_sha=" in body  # empty value OK
```

Add `from datetime import date` at top of the T2 test module (with the Path import).

Note: **clist / `heartbeat.taxonomy` / first_seen commit are intentionally Task 3** — T2 covers fetch→guard→YAML write (+ CLI exit 0). T3 extends the same function with step f.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement dump_yaml signature change + refresh_taxonomy_once**

Logic order per spec §2.1 a–e (git=False; **not** f yet):
1. Try fetch → on exception/empty mapped after normalize → status fail, no write
2. Build candidate members; merge prior `name_zh` from HEAD file; optional name_map overlay (failures leave prior names)
3. `guard_ok` → fail keeps HEAD
4. If semantic equal → `skipped_no_diff`
5. Else write `stock_sw_l2.yaml`; if membership/sw_l2 delta non-zero → `bump_map_version` + `patch_map_version_header` on three files; else keep version
6. Return status dict (`taxonomy_fetch`, `map_version`, deltas…)

Git (`git=True`): CLI `--git`; config user, add taxonomy paths, commit, `pull --rebase --autostash`, then `git push` (no `--force`).

**Publish failure (any cause):**
- Rebase conflict → `rebase --abort`
- Push rejected / network / hook after local commit → **same recovery**: restore taxonomy paths (and any staged first_seen/heartbeat from this step) to `ORIG_HEAD` / `@{upstream}` / pre-commit tree so workspace YAML matches **published** tip — never leave an unpushed local commit that sync would read
- Set `taxonomy_fetch=push_fail`, `taxonomy_commit=unpushed`
- **Do not** set `TAXONOMY_HEAD_SHA` / write a non-empty `taxonomy_head_sha` to `GITHUB_OUTPUT`

**Publish success only:** set `os.environ["TAXONOMY_HEAD_SHA"]=git rev-parse HEAD` and `taxonomy_head_sha=<sha>` in `GITHUB_OUTPUT`.

- [ ] **Step 4: Pytest focused**

Run: `.venv/bin/pytest tests/test_refresh_taxonomy.py tests/test_fetch_sw_normalize.py -q`  
Expected: PASS (kwargs optional — normalize tests unchanged)

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
- Consumes: `load_universe_codes`, `load_quarantine_codes`, `fetch_clist_all_a`, `scripts.common.em_client._infer_ts_code`, calendar `trading_days_inclusive` / `trade_dates`
- Produces:
  - `parse_em_list_date(f26_val) -> date | None`
  - `clist_row_to_ts_code(row) -> str | None` — production: `_infer_ts_code(f12, row)` then keep only `^\d{6}\.(SH|SZ)$`; **reject BJ** / non-matches
  - `compute_unmapped_metrics(*, clist_rows or fetch, session_asof: date, first_seen_path: str) -> UnmappedMetrics` dataclass:
    - `unmapped_count: int | None`
    - `ipo_unmapped_alert_count: int | None`
    - `yaml_quarantine_size: int`
    - `clist_fetch: str`  # ok|fail
    - updates first_seen file for codes newly seen; new keys store **`session_asof.isoformat()`** (never wall-clock today)
  - Listing age: inclusive trading days from `list_date` (`f26`) or `first_asof` through `session_asof`
  - Injected `clist_rows` may already carry `ts_code` (tests); production fetch path must run `clist_row_to_ts_code` on raw EM rows

- [ ] **Step 1: Failing tests**

```python
from datetime import date

from scripts.taxonomy.unmapped import compute_unmapped_metrics, parse_em_list_date


def test_parse_f26_yyyymmdd_and_ms():
    assert parse_em_list_date("20240105") == date(2024, 1, 5)
    # 2024-01-05 00:00 Asia/Shanghai
    assert parse_em_list_date(1704384000000) == date(2024, 1, 5)
    assert parse_em_list_date(None) is None


def test_unmapped_count_formula(tmp_path, monkeypatch):
    first_seen = tmp_path / "unmapped_first_seen.json"
    first_seen.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: ["000001.SZ"],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    clist = [
        {"ts_code": "000001.SZ", "f26": "20200101"},
        {"ts_code": "000002.SZ", "f26": "20200101"},
    ]
    m = compute_unmapped_metrics(
        clist_rows=clist,
        session_asof=date(2024, 1, 10),
        first_seen_path=str(first_seen),
    )
    assert m.clist_fetch == "ok"
    assert m.unmapped_count == 1
    # 2020 list_date → many trading days ≥ 3
    assert m.ipo_unmapped_alert_count == 1


def test_ipo_alert_via_f26_not_first_seen(tmp_path, monkeypatch):
    """f26 must drive IPO≥3; empty first_seen must not be required."""
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.trading_days_inclusive",
        lambda a, b: [d for d in [
            date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        ] if a <= d <= b],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")
    m = compute_unmapped_metrics(
        clist_rows=[{"ts_code": "000002.SZ", "f26": "20240102"}],  # or ms 1704124800000
        session_asof=date(2024, 1, 5),
        first_seen_path=str(first_seen),
    )
    # inclusive [01-02 .. 01-05] = 4 ≥ 3
    assert m.ipo_unmapped_alert_count == 1


def test_first_seen_writes_session_asof(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.trading_days_inclusive",
        lambda a, b: [a] if a == b else [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")
    asof = date(2024, 1, 10)
    compute_unmapped_metrics(
        clist_rows=[{"ts_code": "000003.SZ", "f26": None}],
        session_asof=asof,
        first_seen_path=str(first_seen),
    )
    data = json.loads(first_seen.read_text(encoding="utf-8"))
    assert data["000003.SZ"] == "2024-01-10"


def test_ipo_alert_first_seen(tmp_path, monkeypatch):
    # Use a tiny synthetic calendar: 2024-01-02,03,04,05 (weekdays)
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.trading_days_inclusive",
        lambda a, b: [d for d in [
            date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        ] if a <= d <= b],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_universe_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.taxonomy.unmapped.load_quarantine_codes",
        lambda: set(),
    )
    first_seen = tmp_path / "fs.json"
    first_seen.write_text('{"000002.SZ": "2024-01-02"}', encoding="utf-8")
    m = compute_unmapped_metrics(
        clist_rows=[{"ts_code": "000002.SZ", "f26": None}],
        session_asof=date(2024, 1, 5),
        first_seen_path=str(first_seen),
    )
    # inclusive [01-02 .. 01-05] = 4 trading days ≥ 3
    assert m.ipo_unmapped_alert_count == 1


def test_clist_fail_returns_null_counts(tmp_path, monkeypatch):
    first_seen = tmp_path / "fs.json"
    first_seen.write_text("{}", encoding="utf-8")

    def _boom(**kwargs):
        raise RuntimeError("em down")

    m = compute_unmapped_metrics(
        clist_fetch=_boom,
        session_asof=date(2024, 1, 10),
        first_seen_path=str(first_seen),
    )
    assert m.clist_fetch == "fail"
    assert m.unmapped_count is None
    assert m.ipo_unmapped_alert_count is None
```

`compute_unmapped_metrics` signature: either `clist_rows=` **or** `clist_fetch=` callable; not both required. Prefer keyword-only.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `unmapped.py`**

Production fetch path: `fetch_clist_all_a(["f12","f13","f14","f26"])` → each row through `clist_row_to_ts_code` (`_infer_ts_code` + SH/SZ regex). Tests may inject `{"ts_code","f26"}` directly. Never write `0` on failure.

- [ ] **Step 4: Wire into `refresh_taxonomy_once` step f** — call `compute_unmapped_metrics(..., session_asof=session_asof)`; write `heartbeat.taxonomy` via **`merge_heartbeat_taxonomy(fields)`** (dedicated helper: load JSON → `data["taxonomy"]=fields` → write; **do not** call `write_heartbeat(job=...)` so no `last_success` injection). When `git=True` and heartbeat/first_seen changed, commit those paths (even if YAML skipped) with the same publish-failure recovery as T2.

Heartbeat `data["taxonomy"]` shape (no `last_success`):

```python
{
  "taxonomy_fetch": "...",
  "clist_fetch": "ok|fail",
  "unmapped_count": 123,  # or null
  "ipo_unmapped_alert_count": 0,
  "yaml_quarantine_size": 67,
  "map_version": "sw2021-v1",
  "taxonomy_commit": "abc" | "unpushed" | "",
  "updated_at": "<iso Z>",
}
```

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
- Consumes:
  - `compute_unmapped_metrics` once per `main()` for `session_asof`
  - **`taxonomy_fetch` status:** prefer `os.environ.get("TAXONOMY_FETCH")` if set; else read `heartbeat["taxonomy"]["taxonomy_fetch"]` written in taxonomy step f (local runs / missing env)
- Produces: `run_meta.unmapped_count` on **asof row only**; other days keep previous DB value (do not overwrite with today's clist). Append taxonomy warn to `warn` when asof.

- [ ] **Step 1: Failing tests**

```python
from dataclasses import dataclass
from datetime import date


@dataclass
class _UM:
    unmapped_count: int | None
    ipo_unmapped_alert_count: int | None
    yaml_quarantine_size: int
    clist_fetch: str


def test_asof_run_meta_unmapped_not_literal_zero(tmp_path, monkeypatch):
    from scripts.daily_run import _run_meta_unmapped_fields

    asof = date(2024, 1, 10)
    um = _UM(3, 1, 0, "ok")
    fields = _run_meta_unmapped_fields(D=asof, session_asof=asof, um=um)
    assert fields["unmapped_count"] == 3
    prior = _run_meta_unmapped_fields(
        D=date(2024, 1, 9), session_asof=asof, um=um, prior_unmapped_count=9
    )
    assert prior["unmapped_count"] == 9  # not today's 3


def test_warn_appends_taxonomy():
    from scripts.daily_run import _append_taxonomy_warn

    # Match process_day: "passed" is cleared to "" before warn append
    assert (
        _append_taxonomy_warn("limit_coverage_asof<0.80", ipo_alert=1, taxonomy_fetch="ok", clist_fetch="ok")
        == "limit_coverage_asof<0.80; taxonomy: ipo_unmapped_alert=1"
    )
    assert "taxonomy_fetch=fail" in _append_taxonomy_warn(
        "", ipo_alert=0, taxonomy_fetch="fail", clist_fetch="ok"
    )
    assert "taxonomy_fetch=push_fail" in _append_taxonomy_warn(
        "", ipo_alert=0, taxonomy_fetch="push_fail", clist_fetch="ok"
    )


def test_git_sha_prefers_taxonomy_head_then_github_sha(monkeypatch):
    from scripts.daily_run import _resolve_git_sha

    monkeypatch.setenv("TAXONOMY_HEAD_SHA", "deadbeef")
    monkeypatch.setenv("GITHUB_SHA", "checkout1")
    assert _resolve_git_sha() == "deadbeef"

    monkeypatch.delenv("TAXONOMY_HEAD_SHA", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "checkout1")
    # push_fail / unpushed: keep checkout SHA — never fall through to local HEAD
    assert _resolve_git_sha() == "checkout1"


def test_ipo_alert_does_not_flip_evaluate_ok():
    """Soft gate: ipo_unmapped_alert>0 must not make status partial when coverage passes."""
    from scripts.common.coverage import CoverageMetrics, evaluate_ok
    from scripts.daily_run import _append_taxonomy_warn

    m = CoverageMetrics(
        bar_coverage=1.0,
        computable_coverage=1.0,
        limit_coverage_asof=1.0,
        mapped_sync_coverage=1.0,
    )
    asof = date(2024, 1, 10)
    decision = evaluate_ok(asof, asof, m)
    assert decision.status == "ok"
    warn = _append_taxonomy_warn(
        "" if decision.reason == "passed" else decision.reason,
        ipo_alert=2,
        taxonomy_fetch="ok",
        clist_fetch="ok",
    )
    assert decision.status == "ok"
    assert "ipo_unmapped_alert=2" in warn
```

**`upsert_rows` is `INSERT OR REPLACE` on the full dict** (`scripts/common/db.py`). Nail this:

```python
def _run_meta_unmapped_fields(*, D, session_asof, um, prior_unmapped_count=None):
    if D == session_asof:
        return {"unmapped_count": um.unmapped_count}  # may be None → SQL NULL
    # non-asof: keep previous DB value (caller SELECTs first; default None only if no row)
    return {"unmapped_count": prior_unmapped_count}
```

In `process_day` before upsert:

```python
prior_u = None
if D != session_asof:
    row = conn.execute(
        "SELECT unmapped_count FROM run_meta WHERE trade_date=?",
        (D.isoformat(),),
    ).fetchone()
    prior_u = row[0] if row else None
# ... build run_meta dict including **_run_meta_unmapped_fields(...)
```

**git_sha:** `_resolve_git_sha()` =
1. non-empty `os.environ.get("TAXONOMY_HEAD_SHA")` (YAML push succeeded), else
2. `os.environ.get("GITHUB_SHA", "")` (Actions checkout SHA), else
3. `""` locally if unset  
**Never** `git rev-parse HEAD` as fallback — that records unpublished tip on `push_fail`/`unpushed`.

**taxonomy_fetch for warn:** `_load_taxonomy_fetch()` → env `TAXONOMY_FETCH` if set, else `heartbeat.json` → `taxonomy.taxonomy_fetch`, else `"ok"` (no warn).

Warn append only on asof when `taxonomy_fetch` in (`fail`,`push_fail`) or `ipo_unmapped_alert_count>0` or `clist_fetch==fail`.

Preserve heartbeat: after `write_heartbeat(job=daily_run)`, assert taxonomy key remains (existing db.py keeps dict siblings — add test).

- [ ] **Step 2: Implement** helpers + wire `process_day` (remove literal `unmapped_count: 0`).
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
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          python scripts/taxonomy/refresh_taxonomy.py --git
          # always exit 0; writes taxonomy_fetch= / taxonomy_head_sha= to GITHUB_OUTPUT
```

On the existing `daily_run` step only, add:

```yaml
        env:
          TAXONOMY_HEAD_SHA: ${{ steps.taxonomy.outputs.taxonomy_head_sha }}
          TAXONOMY_FETCH: ${{ steps.taxonomy.outputs.taxonomy_fetch }}
```

Refresh CLI must append to `$GITHUB_OUTPUT`:

```text
taxonomy_fetch=ok
taxonomy_head_sha=<sha or empty>
```

CLI default `session_asof=latest_trade_day()` (optional `--asof YYYY-MM-DD` for tests). Do **not** use `continue-on-error: true`. Do **not** gate sync on taxonomy success (sync always runs next).

- [ ] **Step 2: Local sanity**

Run: `python scripts/taxonomy/refresh_taxonomy.py --help`  
Expected: shows `--git` / `--asof` flags

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily-trend.yml
git commit -m "$(cat <<'EOF'
ci: run taxonomy refresh before mapped-universe sync

EOF
)"
```

(Workflow-only commit; GITHUB_OUTPUT writing lands in T2/T3.)

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
| taxonomy_fetch → warn (env + heartbeat) | T4 / T5 |
| soft gate (IPO never flips evaluate_ok) | T4 |
| session_asof on refresh / first_seen | T2 / T3 |
| unpin sw2021-v1 | T0 |
| no tree-out bars | Global / T5 (sync unchanged) |
| todo leftover warmup + Next E | T6 |

## Out of slice

Tree-out bars warmup, Spec E, engine_state, BJ quarantine rows, PR-gated publish, hard unmapped partial, SW annual >80 auto-apply.

---

## Plan self-review notes

1. **Coverage:** All final-review spec bullets map to T0–T6.  
2. **Placeholders:** Cleared in plan-CR patch (2026-10-08): full T2/T3 fixtures; `f26` ms `1704384000000` → 2024-01-05 CST; T4 upsert/git_sha helpers named.  
3. **Types:** `UnmappedMetrics` / `_UM` test double / membership helpers consistent; env **`TAXONOMY_HEAD_SHA`** + **`TAXONOMY_FETCH`** (daily_run); heartbeat fallback for local.  
4. **Plan CR (2026-10-08) true fixes:** T2/T3 no `...`; T4 `INSERT OR REPLACE` + prior SELECT; `dump_yaml` kwargs optional; T1 tests for `mapped_count`/`patch_map_version_header`; T5 exports `taxonomy_head_sha` to daily_run.  
5. **Indep plan-CR (2026-10-08) true fixes:** C1 git_sha = TAXONOMY_HEAD_SHA → GITHUB_SHA (never local HEAD); any publish fail restores workspace; C2 `session_asof` on refresh/CLI; C3 wire `TAXONOMY_FETCH` + heartbeat read; I1 T2 orchestration fixtures; I2 f26 IPO≥3 assert; I3 `_infer_ts_code` + SH/SZ; I4 soft-gate evaluate_ok test; I5 push-fail recovery; M1 warn base `""`; M2 workflow-only T5 commit; M3 `merge_heartbeat_taxonomy` only.

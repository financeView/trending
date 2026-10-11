# Protocol B: hard_freeze stamp + hard gates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a single-row `hard_freeze_pass_meta` stamp after a successful hard-freeze pass; fail sync on freeze/stamp errors; fail `daily_run` when stamp ≠ yaml; keep Actions bars cache saveable on sync failure (cache B).

**Architecture:** Extend `scripts/common/hard_freeze.py` with yaml-homologous load (N + `param_version`, respect `METRICS_PARAMS_YAML`), stamp ensure/read/write, and shared check. `sync_bars_sample.run_spec_e_passes` hard-fails freeze+stamp (board_calc stays warn). `daily_run.main` checks once after calendar/empty-queue skip, before `process_day`. Workflow: `actions/cache/restore` + `actions/cache/save` with `always() && cache-hit != 'true'`.

**Tech Stack:** Python 3.11, SQLite `bars.db`, PyYAML, pytest, GitHub Actions `actions/cache` restore/save v4.

## Global Constraints

- Spec: [`2026-10-10-protocol-b-hard-freeze-stamp-design.md`](../specs/2026-10-10-protocol-b-hard-freeze-stamp-design.md) (final; CR patches included)
- Cross: Spec E §2.1 / §4.3.1; Spec F §4.3.1 (cache B)
- Stamp table: `hard_freeze_pass_meta` id=1 only; compare **both** N and `param_version`
- hard_freeze fail or stamp fail → sync non-zero; **never** `write_sync_complete(true)` on that path
- board_calc remains warn; separate try from freeze
- Empty default mapped universe (`codes_from_universe()` with no `--from-universe`) → sync non-zero, no stamp; `--from-universe` empty → no stamp only
- incomplete OHLC: still freeze+stamp; `sync_complete=false`; exit 0
- `daily_run` stamp check after non-trading / empty-queue skip; not inside `process_day`
- Cache key stays `bars-${{ github.run_id }}` (no `run_attempt`); forbid `save-always:`
- Out of slice: `paper_book` gate, metrics auto-pass, limit_rule / incomplete×asof product, streak algorithm changes
- Do not commit dirty `data/cache/*` in feat commits
- Prefer `.venv/bin/pytest` when present

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/hard_freeze.py` | `resolve_metrics_yaml_path`; `load_hard_freeze_pass_config`; stamp ensure/read/write; `check_hard_freeze_stamp` |
| `scripts/sync_bars_sample.py` | hard-fail freeze+stamp; empty mapped; order before `write_sync_complete` |
| `scripts/daily_run.py` | call check after skip, before `process_day` |
| `scripts/check_hard_freeze_stamp.py` | thin CLI → same check |
| `.github/workflows/daily-trend.yml` | sync restore/save split (cache B) |
| `tests/test_hard_freeze_stamp.py` | stamp + loader + check |
| `tests/test_sync_hard_freeze_gate.py` | sync fail/incomplete/empty/board isolation |
| `tests/test_daily_run_hard_freeze_stamp.py` | daily_run gate + skip |
| `tests/test_p2_workflow_order.py` | static cache B asserts |
| `docs/...` runbook / Spec status / `todo.md` | Done-when |

```text
Task 0 (loader + stamp helpers)
  └─► Task 1 (sync hard-fail + write stamp)
        └─► Task 2 (daily_run check + CLI)
              └─► Task 3 (workflow cache B + static tests)
                    └─► Task 4 (runbook + todo + Spec status)
```

---

### Task 0: Yaml loader + stamp table helpers

**Files:**
- Modify: `scripts/common/hard_freeze.py`
- Create: `tests/test_hard_freeze_stamp.py`
- Keep: `load_hard_freeze_min_suspend_days` as thin wrapper (existing tests)

**Interfaces:**
- Produces:
  - `resolve_metrics_yaml_path(path: Path | None = None) -> Path`
  - `HardFreezePassConfig(min_suspend_days: int, param_version: str)` (dataclass or NamedTuple)
  - `load_hard_freeze_pass_config(path: Path | None = None) -> HardFreezePassConfig`
  - `ensure_hard_freeze_pass_meta(conn) -> None`
  - `write_hard_freeze_pass_meta(conn, *, n: int, param_version: str, rows_touched: int | None = None, rewritten_at: str | None = None) -> None`
  - `read_hard_freeze_pass_meta(conn) -> dict | None`  # keys: n, param_version, rewritten_at, rows_touched
  - `check_hard_freeze_stamp(bars_path: str | None = None, yaml_path: Path | None = None) -> int`  # 0 ok, 1 fail

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hard_freeze_stamp.py
from pathlib import Path

from scripts.common.bars import bars_conn
from scripts.common.hard_freeze import (
    check_hard_freeze_stamp,
    ensure_hard_freeze_pass_meta,
    load_hard_freeze_pass_config,
    read_hard_freeze_pass_meta,
    resolve_metrics_yaml_path,
    write_hard_freeze_pass_meta,
)


def test_resolve_respects_env(tmp_path, monkeypatch):
    p = tmp_path / "m.yaml"
    p.write_text("param_version: t\nhard_freeze_min_suspend_days: 7\n", encoding="utf-8")
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(p))
    assert resolve_metrics_yaml_path() == Path(p)


def test_load_pass_config_reads_n_and_version(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "param_version: p-test\nhard_freeze_min_suspend_days: 11\n",
        encoding="utf-8",
    )
    cfg = load_hard_freeze_pass_config(p)
    assert cfg.min_suspend_days == 11
    assert cfg.param_version == "p-test"


def test_write_read_stamp_roundtrip(tmp_path):
    conn = bars_conn(str(tmp_path / "b.db"))
    ensure_hard_freeze_pass_meta(conn)
    write_hard_freeze_pass_meta(
        conn, n=20, param_version="p05-v3", rows_touched=42, rewritten_at="2026-10-10T00:00:00Z"
    )
    meta = read_hard_freeze_pass_meta(conn)
    assert meta["n"] == 20
    assert meta["param_version"] == "p05-v3"
    assert meta["rows_touched"] == 42
    assert meta["rewritten_at"] == "2026-10-10T00:00:00Z"


def test_write_upserts_single_row(tmp_path):
    conn = bars_conn(str(tmp_path / "b.db"))
    write_hard_freeze_pass_meta(conn, n=20, param_version="a")
    write_hard_freeze_pass_meta(conn, n=25, param_version="b")
    n = conn.execute("SELECT COUNT(*) FROM hard_freeze_pass_meta").fetchone()[0]
    assert n == 1
    assert read_hard_freeze_pass_meta(conn)["n"] == 25


def test_check_ok_mismatch_missing(tmp_path, monkeypatch):
    db = tmp_path / "b.db"
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(db))
    assert check_hard_freeze_stamp(str(db)) == 1  # missing
    write_hard_freeze_pass_meta(conn, n=20, param_version="p05-v3")
    assert check_hard_freeze_stamp(str(db)) == 0
    write_hard_freeze_pass_meta(conn, n=99, param_version="p05-v3")
    assert check_hard_freeze_stamp(str(db)) == 1  # N mismatch
    write_hard_freeze_pass_meta(conn, n=20, param_version="other")
    assert check_hard_freeze_stamp(str(db)) == 1  # param_version mismatch
```

- [ ] **Step 2: Run tests — expect FAIL (imports / missing symbols)**

Run: `.venv/bin/pytest tests/test_hard_freeze_stamp.py -q`

- [ ] **Step 3: Implement helpers in `scripts/common/hard_freeze.py`**

Add (keep existing `apply_hard_freeze_flags`; rewrite loader):

```python
import os
from dataclasses import dataclass
from datetime import datetime, timezone

# ... existing imports ...

def resolve_metrics_yaml_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("METRICS_PARAMS_YAML")
    if env:
        return Path(env)
    return _DEFAULT_METRICS


@dataclass(frozen=True)
class HardFreezePassConfig:
    min_suspend_days: int
    param_version: str


def load_hard_freeze_pass_config(path: Optional[Path] = None) -> HardFreezePassConfig:
    p = resolve_metrics_yaml_path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    n = int(raw.get("hard_freeze_min_suspend_days") or 20)
    pv = str(raw.get("param_version") or "").strip()
    if not pv:
        raise ValueError("param_version missing in %s" % p)
    return HardFreezePassConfig(min_suspend_days=n, param_version=pv)


def load_hard_freeze_min_suspend_days(path: Optional[Path] = None) -> int:
    return load_hard_freeze_pass_config(path).min_suspend_days


_HARD_FREEZE_PASS_META_DDL = """
CREATE TABLE IF NOT EXISTS hard_freeze_pass_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  hard_freeze_min_suspend_days INTEGER NOT NULL,
  param_version TEXT NOT NULL,
  rewritten_at TEXT NOT NULL,
  rows_touched INTEGER
);
"""


def ensure_hard_freeze_pass_meta(conn) -> None:
    conn.executescript(_HARD_FREEZE_PASS_META_DDL)
    conn.commit()


def write_hard_freeze_pass_meta(
    conn,
    *,
    n: int,
    param_version: str,
    rows_touched: Optional[int] = None,
    rewritten_at: Optional[str] = None,
) -> None:
    ensure_hard_freeze_pass_meta(conn)
    ts = rewritten_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO hard_freeze_pass_meta (
          id, hard_freeze_min_suspend_days, param_version, rewritten_at, rows_touched
        ) VALUES (1,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          hard_freeze_min_suspend_days=excluded.hard_freeze_min_suspend_days,
          param_version=excluded.param_version,
          rewritten_at=excluded.rewritten_at,
          rows_touched=excluded.rows_touched
        """,
        (int(n), str(param_version), ts, rows_touched),
    )
    conn.commit()


def read_hard_freeze_pass_meta(conn) -> Optional[dict]:
    ensure_hard_freeze_pass_meta(conn)
    row = conn.execute(
        """
        SELECT hard_freeze_min_suspend_days, param_version, rewritten_at, rows_touched
        FROM hard_freeze_pass_meta WHERE id=1
        """
    ).fetchone()
    if not row:
        return None
    return {
        "n": int(row[0]),
        "param_version": str(row[1]),
        "rewritten_at": str(row[2]),
        "rows_touched": row[3],
    }


def check_hard_freeze_stamp(
    bars_path: Optional[str] = None,
    yaml_path: Optional[Path] = None,
) -> int:
    """Return 0 if stamp matches yaml; 1 if missing or mismatch. Prints stderr reason."""
    import sys
    from scripts.common.bars import DEFAULT_BARS_DB, bars_conn

    cfg = load_hard_freeze_pass_config(yaml_path)
    path = bars_path or DEFAULT_BARS_DB
    conn = bars_conn(path)
    try:
        meta = read_hard_freeze_pass_meta(conn)
    finally:
        conn.close()
    if meta is None:
        print(
            "[hard_freeze_stamp] missing stamp — run full sync (hard_freeze pass) first",
            file=sys.stderr,
        )
        return 1
    if meta["n"] != cfg.min_suspend_days or meta["param_version"] != cfg.param_version:
        print(
            "[hard_freeze_stamp] mismatch stamp=(n=%s,pv=%s) yaml=(n=%s,pv=%s) "
            "— run full sync to refresh flags+stamp"
            % (meta["n"], meta["param_version"], cfg.min_suspend_days, cfg.param_version),
            file=sys.stderr,
        )
        return 1
    return 0
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `.venv/bin/pytest tests/test_hard_freeze_stamp.py tests/test_hard_freeze.py tests/test_hard_freeze_config.py -q`

- [ ] **Step 5: Commit**

```bash
git add scripts/common/hard_freeze.py tests/test_hard_freeze_stamp.py
git commit -m "$(cat <<'EOF'
feat(hard_freeze): stamp table helpers and yaml-homologous loader

EOF
)"
```

---

### Task 1: Sync hard-fail freeze + write stamp

**Files:**
- Modify: `scripts/sync_bars_sample.py` (`run_spec_e_passes`, `main` around pass_codes / return)
- Create: `tests/test_sync_hard_freeze_gate.py`
- May touch: `tests/test_sync_spec_e_passes.py` if mocks need `load_hard_freeze_pass_config`

**Interfaces:**
- Consumes: Task 0 loaders + `write_hard_freeze_pass_meta`
- Produces: `run_spec_e_passes` raises on freeze/stamp fail; stamps on success with non-empty codes; `main` returns 1 on freeze fail / empty mapped; incomplete still stamps + `sync_complete=false`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_hard_freeze_gate.py
import datetime as dt

from scripts.common.bars import bars_conn
from scripts.common.hard_freeze import read_hard_freeze_pass_meta
from scripts.sync_bars_sample import main, run_spec_e_passes


def test_freeze_success_writes_stamp(tmp_path, monkeypatch):
    db = tmp_path / "b.db"
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(db))
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 7,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
    meta = read_hard_freeze_pass_meta(conn)
    assert meta["n"] == 20
    assert meta["param_version"] == "p-x"
    assert meta["rows_touched"] == 7


def test_freeze_raise_propagates_no_stamp(tmp_path, monkeypatch):
    conn = bars_conn(str(tmp_path / "b.db"))
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    try:
        run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
        assert False, "expected raise"
    except RuntimeError:
        pass
    assert read_hard_freeze_pass_meta(conn) is None


def test_empty_codes_no_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(tmp_path / "b.db"))
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    run_spec_e_passes(conn, [], session_asof=dt.date(2024, 1, 9))
    assert read_hard_freeze_pass_meta(conn) is None


def test_main_empty_mapped_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "b.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )
    wrote = {"n": 0}

    def _wsc(*a, **k):
        wrote["n"] += 1

    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    rc = main(["--end", "2024-01-09"])
    assert rc == 1
    assert wrote["n"] == 0


def test_main_freeze_fail_no_sync_complete_true(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "b.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )

    def _boom(*a, **k):
        raise RuntimeError("freeze fail")

    monkeypatch.setattr("scripts.sync_bars_sample.run_spec_e_passes", _boom)
    outs = []

    def _wsc(complete, elapsed_min=0.0):
        outs.append(complete)

    monkeypatch.setattr("scripts.sync_bars_sample.write_sync_complete", _wsc)
    rc = main(["--end", "2024-01-09"])
    assert rc == 1
    assert outs == []  # must not write sync_complete on fail path


def test_stamp_write_fail_no_sync_complete(tmp_path, monkeypatch):
    """Spec §5.7: write_hard_freeze_pass_meta raise → sync non-zero, no sync_complete."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    monkeypatch.setattr(
        "scripts.sync_bars_sample.bars_conn",
        lambda: bars_conn(str(tmp_path / "b.db")),
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.codes_from_universe",
        lambda *a, **k: ["600000.SH"],
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_ohlc", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.skip_flags", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 1,
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.write_hard_freeze_pass_meta",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stamp fail")),
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    outs = []
    monkeypatch.setattr(
        "scripts.sync_bars_sample.write_sync_complete",
        lambda complete, elapsed_min=0.0: outs.append(complete),
    )
    rc = main(["--end", "2024-01-09"])
    assert rc == 1
    assert outs == []


def test_board_calc_warn_does_not_block_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    conn = bars_conn(str(tmp_path / "b.db"))
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 1,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "board_calc_v1"})(),
    )
    monkeypatch.setattr(
        "scripts.common.board_calc.apply_board_calc",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bc")),
    )
    run_spec_e_passes(conn, ["600000.SH"], session_asof=dt.date(2024, 1, 9))
    assert read_hard_freeze_pass_meta(conn)["param_version"] == "p-x"


def test_incomplete_still_stamps(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p-x\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    calls = {"complete": None}

    def _wsc(complete, elapsed_min=0.0):
        calls["complete"] = complete

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
        "scripts.sync_bars_sample.latest_trade_day", lambda: dt.date(2024, 1, 9)
    )
    monkeypatch.setattr(
        "scripts.common.hard_freeze.apply_hard_freeze_flags",
        lambda *a, **k: 2,
    )
    monkeypatch.setattr(
        "scripts.eval.costs.load_costs",
        lambda: type("C", (), {"limit_rule": "vendor_fields"})(),
    )
    rc = main(["--end", "2024-01-09", "--max-codes", "1", "--skip-flags"])
    assert rc == 0
    assert calls["complete"] is False
    conn = bars_conn(str(db))
    assert read_hard_freeze_pass_meta(conn)["n"] == 20
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_sync_hard_freeze_gate.py -q`

- [ ] **Step 3: Rewrite `run_spec_e_passes` + `main` gate**

Replace `run_spec_e_passes` body with:

```python
def run_spec_e_passes(conn, codes, *, session_asof: dt.date) -> None:
    from scripts.common.bars import ensure_bars_columns
    from scripts.common.board_calc import apply_board_calc
    from scripts.common.hard_freeze import (
        apply_hard_freeze_flags,
        load_hard_freeze_pass_config,
        write_hard_freeze_pass_meta,
    )
    from scripts.eval.costs import load_costs

    ensure_bars_columns(conn)
    cfg = load_hard_freeze_pass_config()
    if codes:
        nf = apply_hard_freeze_flags(conn, codes, n=cfg.min_suspend_days)
        write_hard_freeze_pass_meta(
            conn,
            n=cfg.min_suspend_days,
            param_version=cfg.param_version,
            rows_touched=nf,
        )
        if nf:
            print("[sync_bars] hard_freeze rows=%d" % nf)
    try:
        costs = load_costs()
        nb = apply_board_calc(
            conn, codes, session_asof=session_asof, limit_rule=costs.limit_rule
        )
        if nb:
            print("[sync_bars] board_calc rows=%d" % nb)
    except Exception as e:  # noqa: BLE001
        print("[sync_bars] warn: board_calc skipped: %s" % e, file=sys.stderr)
```

In `main`, after building `pass_codes` (replace the old unconditional `run_spec_e_passes` + always-`return 0`):

```python
    try:
        if not args.from_universe and not pass_codes:
            print("[sync_bars] error: empty mapped universe", file=sys.stderr)
            return 1
        run_spec_e_passes(conn, pass_codes, session_asof=session_asof)
    except Exception as e:  # noqa: BLE001
        print("[sync_bars] error: hard_freeze/stamp failed: %s" % e, file=sys.stderr)
        return 1
    finally:
        conn.close()
    elapsed_min = (dt.datetime.utcnow() - started).total_seconds() / 60.0
    write_sync_complete(complete, elapsed_min)
    return 0
```

Notes: (1) `return` inside `try`/`except` still runs `finally`, then leaves — so empty-universe / freeze-fail never reach `write_sync_complete`. (2) Remove any later duplicate `conn.close()`.

- [ ] **Step 4: Retarget loader mocks in existing sync tests**

`run_spec_e_passes` will call `load_hard_freeze_pass_config`, not `load_hard_freeze_min_suspend_days`. Old mocks of the latter become no-ops (tests may still pass via the real `a_share_daily.yaml`, but that is accidental).

In **both** files, replace the `load_hard_freeze_min_suspend_days` monkeypatch with either:

```python
from scripts.common.hard_freeze import HardFreezePassConfig

monkeypatch.setattr(
    "scripts.common.hard_freeze.load_hard_freeze_pass_config",
    lambda path=None: HardFreezePassConfig(min_suspend_days=20, param_version="p05-v3"),
)
```

or set `METRICS_PARAMS_YAML` to a temp yaml that includes both keys.

Files (must touch):
- `tests/test_sync_spec_e_passes.py` (two sites that currently patch `load_hard_freeze_min_suspend_days`)
- `tests/test_sync_from_universe.py` (one site)

- [ ] **Step 5: Run — expect PASS**

Run: `.venv/bin/pytest tests/test_sync_hard_freeze_gate.py tests/test_sync_spec_e_passes.py tests/test_sync_from_universe.py tests/test_hard_freeze_stamp.py -q`

- [ ] **Step 6: Commit**

```bash
git add scripts/sync_bars_sample.py tests/test_sync_hard_freeze_gate.py \
  tests/test_sync_spec_e_passes.py tests/test_sync_from_universe.py
git commit -m "$(cat <<'EOF'
feat(sync): hard-fail hard_freeze and write pass stamp

EOF
)"
```

---

### Task 2: `daily_run` gate + CLI

**Files:**
- Modify: `scripts/daily_run.py` (`main` after queue finalized)
- Create: `scripts/check_hard_freeze_stamp.py`
- Create: `tests/test_daily_run_hard_freeze_stamp.py`

**Interfaces:**
- Consumes: `check_hard_freeze_stamp`
- Produces: `daily_run` returns non-zero on mismatch when it would process days; skip paths return 0 without check

- [ ] **Step 1: Write failing tests**

```python
# tests/test_daily_run_hard_freeze_stamp.py
from datetime import date

from scripts.common.bars import bars_conn
from scripts.common.hard_freeze import write_hard_freeze_pass_meta
from scripts.daily_run import main
from scripts.taxonomy.unmapped import UnmappedMetrics


def _ok_um(**k):
    return UnmappedMetrics(
        unmapped_count=0,
        ipo_unmapped_alert_count=0,
        yaml_quarantine_size=0,
        clist_fetch="ok",
    )


def test_daily_run_fails_without_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    bars_conn(str(db))
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    called = {"n": 0}

    def _pd(*a, **k):
        called["n"] += 1
        return "ok"

    monkeypatch.setattr("scripts.daily_run.process_day", _pd)
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 1
    assert called["n"] == 0


def test_daily_run_ok_with_matching_stamp(tmp_path, monkeypatch):
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=20, param_version="p05-v3")
    conn.close()
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    monkeypatch.setattr("scripts.daily_run.process_day", lambda *a, **k: "ok")
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 0


def test_daily_run_fails_n_mismatch(tmp_path, monkeypatch):
    """Spec §5.3: stamp N ≠ yaml → daily_run non-zero; process_day not called."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=99, param_version="p05-v3")
    conn.close()
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    called = {"n": 0}
    monkeypatch.setattr(
        "scripts.daily_run.process_day",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "ok",
    )
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 1
    assert called["n"] == 0


def test_daily_run_fails_param_version_mismatch(tmp_path, monkeypatch):
    """Spec §5.4: stamp param_version ≠ yaml → daily_run non-zero."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=20, param_version="old-pv")
    conn.close()
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof])
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    called = {"n": 0}
    monkeypatch.setattr(
        "scripts.daily_run.process_day",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "ok",
    )
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 1
    assert called["n"] == 0


def test_skip_non_trading_no_stamp_required(tmp_path, monkeypatch):
    db = tmp_path / "b.db"
    bars_conn(str(db))
    calls = {"n": 0}

    def _check(*a, **k):
        calls["n"] += 1
        return 0

    # Requires Task 2 Step 3 module-level import into scripts.daily_run
    monkeypatch.setattr("scripts.daily_run.check_hard_freeze_stamp", _check)
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 6)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: False)
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-06", "--bars-db", str(db)])
    assert rc == 0
    assert calls["n"] == 0  # Spec §5.11: skip path must not call check


def test_check_called_once_before_process_day(tmp_path, monkeypatch):
    """Spec §5.11: when computing, check exactly once; not inside process_day."""
    y = tmp_path / "m.yaml"
    y.write_text(
        "param_version: p05-v3\nhard_freeze_min_suspend_days: 20\n", encoding="utf-8"
    )
    monkeypatch.setenv("METRICS_PARAMS_YAML", str(y))
    db = tmp_path / "b.db"
    conn = bars_conn(str(db))
    write_hard_freeze_pass_meta(conn, n=20, param_version="p05-v3")
    conn.close()
    calls = {"check": 0, "pd": 0}

    def _check(bars_path=None, yaml_path=None):
        calls["check"] += 1
        return 0

    def _pd(*a, **k):
        calls["pd"] += 1
        return "ok"

    monkeypatch.setattr("scripts.daily_run.check_hard_freeze_stamp", _check)
    monkeypatch.setattr(
        "scripts.daily_run.cal.latest_trade_day", lambda: date(2024, 1, 9)
    )
    monkeypatch.setattr("scripts.daily_run.cal.is_trade_day", lambda x: True)
    monkeypatch.setattr("scripts.daily_run.build_queue", lambda asof: [asof, asof])
    # two days in queue — check must still be once (not per process_day)
    monkeypatch.setattr("scripts.daily_run.compute_unmapped_metrics", _ok_um)
    monkeypatch.setattr("scripts.daily_run.process_day", _pd)
    monkeypatch.setattr("scripts.daily_run.write_heartbeat", lambda *a, **k: None)
    rc = main(["--asof", "2024-01-09", "--bars-db", str(db), "--force-trade-day"])
    assert rc == 0
    assert calls["check"] == 1
    assert calls["pd"] == 2
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_daily_run_hard_freeze_stamp.py -q`

- [ ] **Step 3: Wire `daily_run.main`**

At module top of `scripts/daily_run.py` (with other imports):

```python
from scripts.common.hard_freeze import check_hard_freeze_stamp
```

After empty-queue early return and after `queue` is finalized (before `compute_unmapped_metrics` or immediately before the `for D in queue` loop):

```python
    stamp_rc = check_hard_freeze_stamp(args.bars_db or None)
    if stamp_rc != 0:
        return stamp_rc
```

Do **not** call this before the non-trading-day / empty-queue `return 0` paths. Module-level import lets spies patch `scripts.daily_run.check_hard_freeze_stamp`.

- [ ] **Step 4: Add CLI**

```python
# scripts/check_hard_freeze_stamp.py
"""CLI: exit 0 if hard_freeze stamp matches yaml; else non-zero."""
from __future__ import annotations

import argparse
import sys

from scripts.common.hard_freeze import check_hard_freeze_stamp


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bars-db", default="", help="bars.db path (default cache)")
    args = p.parse_args(argv)
    return check_hard_freeze_stamp(args.bars_db or None)


if __name__ == "__main__":
    raise SystemExit(main())
```

Optional one-liner test: `check_hard_freeze_stamp.main(["--bars-db", str(db)])`.

- [ ] **Step 5: Run — expect PASS**

Run: `.venv/bin/pytest tests/test_daily_run_hard_freeze_stamp.py tests/test_hard_freeze_stamp.py -q`

- [ ] **Step 6: Commit**

```bash
git add scripts/daily_run.py scripts/check_hard_freeze_stamp.py tests/test_daily_run_hard_freeze_stamp.py
git commit -m "$(cat <<'EOF'
feat(daily_run): gate on hard_freeze stamp before process_day

EOF
)"
```

---

### Task 3: Actions cache B + workflow static tests

**Files:**
- Modify: `.github/workflows/daily-trend.yml` (sync job restore/save)
- Modify: `tests/test_p2_workflow_order.py`

**Interfaces:**
- Produces: sync job saves `bars-${{ github.run_id }}` when restore missed exact key, including after sync step failure; metrics key unchanged

- [ ] **Step 1: Write failing static asserts**

Extend `tests/test_p2_workflow_order.py`:

```python
def test_sync_cache_restore_save_protocol_b():
    text = Path(".github/workflows/daily-trend.yml").read_text(encoding="utf-8")
    sync = _sync_block(text)
    assert "actions/cache/restore@v4" in sync
    assert "actions/cache/save@v4" in sync
    assert "save-always" not in text
    assert "run_attempt" not in text
    assert "bars-${{ github.run_id }}" in sync
    # Pin Save step if — do NOT use bare `always()` in sync (Warn incomplete already has it)
    m = re.search(
        r"- name: Save bars cache\n(.*?)(?=\n      - name:|\Z)",
        sync,
        re.S,
    )
    assert m, "Save bars cache step missing"
    save_chunk = m.group(1)
    assert "actions/cache/save@v4" in save_chunk
    assert "always()" in save_chunk or "failure()" in save_chunk
    assert "cache-hit" in save_chunk
    assert "bars-restore" in save_chunk or "bars-${{ github.run_id }}" in save_chunk
    # metrics still exact key
    met = _metrics_block(text)
    assert "bars-${{ github.run_id }}" in met
    assert "cache-hit" in met
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_p2_workflow_order.py::test_sync_cache_restore_save_protocol_b -q`

- [ ] **Step 3: Patch sync job cache steps**

Replace the sync job block:

```yaml
      - name: Restore bars cache
        uses: actions/cache@v4
        with:
          path: data/cache
          key: bars-${{ github.run_id }}
          restore-keys: bars-
```

with:

```yaml
      - name: Restore bars cache
        id: bars-restore
        uses: actions/cache/restore@v4
        with:
          path: data/cache
          key: bars-${{ github.run_id }}
          restore-keys: |
            bars-
```

After the "Warn if sync incomplete" step (end of sync job steps), add:

```yaml
      - name: Save bars cache
        if: ${{ always() && steps.bars-restore.outputs.cache-hit != 'true' }}
        uses: actions/cache/save@v4
        with:
          path: data/cache
          key: bars-${{ github.run_id }}
```

Leave metrics job cache as-is (monolithic restore + exact hit gate is fine).

- [ ] **Step 4: Run full workflow static suite — expect PASS**

Run: `.venv/bin/pytest tests/test_p2_workflow_order.py -q`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/daily-trend.yml tests/test_p2_workflow_order.py
git commit -m "$(cat <<'EOF'
ci: save bars cache on sync failure (Protocol B cache B)

EOF
)"
```

---

### Task 4: Runbook + Done-when docs

**Files:**
- Create: `docs/ops/hard-freeze-stamp-runbook.md` (new `docs/ops/` dir)
- Modify: `todo.md` P0 Protocol B row → done / link Spec+plan
- Modify: Spec Protocol B status → 已落地 + plan link
- Modify: Spec E §4.3.1 status note if it still says「设计中」

- [ ] **Step 1: Write runbook (keep short)**

```markdown
# Hard-freeze stamp runbook (Protocol B)

1. Change `hard_freeze_min_suspend_days` and/or bump `param_version` in `config/metrics/a_share_daily.yaml`.
2. Run a **full sync** on the target `bars.db` (Actions sync job or local `scripts/sync_bars_sample.py`) so hard_freeze pass rewrites flags and UPSERTs `hard_freeze_pass_meta`.
3. Verify: `python scripts/check_hard_freeze_stamp.py` (exit 0) or inspect the stamp row.
4. Then run metrics / `daily_run` / eval.
5. Paper/offline eval: green a stamped `daily_run` first (`paper_book` is not gated).
6. Actions: after hard_freeze failure, start a **new** workflow run to refresh stamp under a new `bars-${{run_id}}`. Do not rely on Re-run failed jobs to overwrite an existing cache key.
```

- [ ] **Step 2: Update `todo.md` + Spec statuses**

- Protocol B row: mark done; link Spec + this plan.
- Spec `2026-10-10-protocol-b-hard-freeze-stamp-design.md`: status → 已落地；link this plan.
- Spec E §4.3.1: change「设计中」→「已落地」if still present.

- [ ] **Step 3: Regression sweep**

Run: `.venv/bin/pytest tests/test_hard_freeze_stamp.py tests/test_sync_hard_freeze_gate.py tests/test_daily_run_hard_freeze_stamp.py tests/test_sync_spec_e_passes.py tests/test_p2_workflow_order.py tests/test_hard_freeze.py -q`

- [ ] **Step 4: Commit**

```bash
git add docs/ops/hard-freeze-stamp-runbook.md todo.md \
  docs/superpowers/specs/2026-10-10-protocol-b-hard-freeze-stamp-design.md \
  docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md
git commit -m "$(cat <<'EOF'
docs: Protocol B hard-freeze stamp runbook and done-when

EOF
)"
```

---

## Spec coverage checklist (self-review)

| Spec item | Task |
|-----------|------|
| `hard_freeze_pass_meta` + helpers | 0 |
| yaml 同源 / `METRICS_PARAMS_YAML` | 0, 1, 2 |
| sync hard-fail freeze; stamp after success | 1 |
| 写戳失败 → sync 非零、无 `sync_complete`（§5.7） | 1 (`test_stamp_write_fail_no_sync_complete`) |
| board_calc warn isolation | 1 |
| empty mapped non-zero; empty codes no stamp | 1 |
| incomplete + stamp + `sync_complete=false` | 1 |
| no `sync_complete=true` on fail | 1 |
| `daily_run` check after skip; §5.3/§5.4 N+pv mismatch via `main` | 2 |
| §5.11 spy：算截面 check×1；skip×0 | 2 |
| optional CLI | 2 |
| cache B：Save 步 `if` 含 always/failure + cache-hit（非 sync 全局 always） | 3 |
| runbook + todo + Spec status | 4 |
| paper_book non-goal | (no task — intentional) |

## Residual ops (not coded)

- Same `run_id` Re-run cannot overwrite saved cache → new workflow run (runbook §6).
- tip yaml ahead of sync SHA → metrics red until next sync (§4.6).

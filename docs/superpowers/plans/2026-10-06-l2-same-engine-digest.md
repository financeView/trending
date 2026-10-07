# L2 Same-Engine + Issue Digests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace L2 tag-any / majority-T interim with same-engine synthetic OHLC → `replay_from_ohlc`; split industry `tag_warm_to_hot` from member count; keep code/`ts_code` columns and add Chinese name columns; show amounts as 亿元 with 3 decimals.

**Architecture:** Pure `synthesize_l2_bars` builds chain-link float_mv returns + HL-ratio proxy from per-day `bars` (never freeze asof tradable). `daily_run` stops calling `aggregate_l2` for L2; L1 stays `aggregate_l1`. Digest joins YAML names at render time; amount cells use a dedicated formatter.

**Tech Stack:** Python 3.11, sqlite3, PyYAML, pandas, pytest, Eastmoney clist (one-shot name patch only).

## Global Constraints

- Spec: [`2026-10-06-l2-same-engine-digest-design.md`](../specs/2026-10-06-l2-same-engine-digest-design.md) (final review passed)
- L2 engine fields from synthetic FSM only; `warm_to_hot_member_count` from `daily_stock` tags
- Skip-day: omit bar from OHLC series; asof row still upserted with SQL NULL engine keys present (not omitted, not `_sql_int_bool`)
- Weights: `bars.float_mv` on day `t`; calendar `prev_trade_date`; no fake `L2.*` in `bars.db`
- No L2 `signal_event`; no L1 same-engine; no RS; do not commit `trade_dates.json` / `heartbeat.json` in feat commits

## File map

| Path | Responsibility |
|------|----------------|
| `scripts/common/db.py` | `daily_l2` cols: `warm_to_hot_member_count`, `amount` in SCHEMA/ALTER/COLS; not `_INT_BOOL_COLS` |
| `scripts/common/universe.py` | `load_stock_sw_l2` pass-through `name_zh` |
| `scripts/taxonomy/patch_stock_names.py` | One-shot EM f14 → patch existing YAML members (not `dump_yaml`) |
| `config/taxonomy/stock_sw_l2.yaml` | Check-in `name_zh` after patch |
| `scripts/metrics/l2_synth.py` | `synthesize_l2_bars` pure |
| `scripts/daily_run.py` | L2 path: synth → `replay_from_ohlc`; member count/amount; no `aggregate_l2` |
| `scripts/issues/digest.py` | Headers, names, `成交额(亿)` |
| `tests/test_l2_synth.py` | Chain returns + skip day |
| `tests/test_c5_same_engine.py` | Identical twins match single `replay_from_ohlc` |
| `tests/test_l2_daily_run_wire.py` | tag≠member count; skip-day NULL; no L2 events |
| `tests/test_l1_digest.py` | Headers / 亿元 / 名称列 |
| `tests/test_universe_yaml_map.py` | loader `name_zh` |
| `README.md` / `todo.md` | Point §0 done / next |

```text
Task 1 (db cols) ─┬─► Task 3 (l2_synth) ─► Task 4 (daily_run wire)
Task 2 (names)   ─┴─► Task 5 (digest) ─────► Task 6 (done-when)
```

---

### Task 1: `daily_l2` schema columns

**Files:**
- Modify: `scripts/common/db.py`
- Test: `tests/test_signal_event_persist.py` (or new `tests/test_daily_l2_cols.py`)

**Interfaces:**
- Produces: `DAILY_BASKET_COLS` includes `warm_to_hot_member_count`, `amount`; upsert round-trips them; `warm_to_hot_member_count` ∉ `_INT_BOOL_COLS`

- [x] **Step 1: Failing test**

```python
def test_daily_l2_upsert_keeps_member_count_and_amount(tmp_path, monkeypatch):
    monkeypatch.setenv("TREND_DB", str(tmp_path / "t.db"))
    from scripts.common import db as dbmod
    conn = dbmod.get_conn()
    dbmod.init_schema(conn)
    dbmod.upsert_daily_l2(
        conn,
        [{
            "trade_date": "2024-01-10",
            "code": "370100",
            "T": None,
            "right_side": None,
            "tag_warm_to_hot": None,
            "tag_warm_to_flat": None,
            "solar_term": None,
            "members_tradable": 0,
            "members_total": 10,
            "warm_to_hot_member_count": 3,
            "amount": 1.5e9,
        }],
    )
    row = conn.execute(
        "SELECT warm_to_hot_member_count, amount, tag_warm_to_hot "
        "FROM daily_l2 WHERE code='370100'"
    ).fetchone()
    assert row[0] == 3
    assert abs(row[1] - 1.5e9) < 1
    assert row[2] is None
```

- [x] **Step 2: Run — expect FAIL** (unknown cols / silent drop)

Run: `pytest tests/test_daily_l2_cols.py::test_daily_l2_upsert_keeps_member_count_and_amount -v`

- [x] **Step 3: Implement**

In `db.py`:
- Add to `CREATE TABLE daily_l2` (and optionally `daily_l1` as NULL-only physical cols): `warm_to_hot_member_count INTEGER`, `amount REAL`
- Append to `DAILY_BASKET_ALTER_COLUMNS` and `DAILY_BASKET_COLS`
- Do **not** add `warm_to_hot_member_count` to `_INT_BOOL_COLS`

- [x] **Step 4: Run — PASS**

- [x] **Step 5: Commit**

```bash
git add scripts/common/db.py tests/test_daily_l2_cols.py
git commit -m "$(cat <<'EOF'
feat(db): daily_l2 warm_to_hot_member_count and amount columns

EOF
)"
```

---

### Task 2: Stock `name_zh` loader + patch script

**Files:**
- Modify: `scripts/common/universe.py` (`load_stock_sw_l2`)
- Create: `scripts/taxonomy/patch_stock_names.py`
- Modify: `config/taxonomy/stock_sw_l2.yaml` (after one-shot patch)
- Test: `tests/test_universe_yaml_map.py`

**Interfaces:**
- Produces: `load_stock_sw_l2()[i]` may include `name_zh: str | None`
- Produces: `patch_stock_names.py` CLI `--in/--out` patches existing members only via EM `f12,f13,f14`

- [x] **Step 1: Failing test**

```python
def test_load_stock_sw_l2_passes_name_zh(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "map_version: sw2021-v1\nmembers:\n"
        "  - {ts_code: 000001.SZ, sw_l2_code: '480300', name_zh: 平安银行}\n"
        "  - {ts_code: 000002.SZ, sw_l2_code: '430100'}\n",
        encoding="utf-8",
    )
    from scripts.common.universe import load_stock_sw_l2
    rows = load_stock_sw_l2(str(p))
    by = {r["ts_code"]: r for r in rows}
    assert by["000001.SZ"]["name_zh"] == "平安银行"
    assert by["000002.SZ"].get("name_zh") in (None, "")
```

- [x] **Step 2: Run — FAIL** (name dropped)

- [x] **Step 3: Loader**

```python
# in load_stock_sw_l2 loop:
name = m.get("name_zh")
name_zh = None if name in (None, "") else str(name)
out.append({"ts_code": ts, "sw_l2_code": code, "name_zh": name_zh})
```

- [x] **Step 4: `patch_stock_names.py`** (do **not** call `dump_yaml`)

```python
"""One-shot: Eastmoney f14 → patch name_zh on existing stock_sw_l2 members."""
# load YAML with yaml.safe_load
# fetch_clist_all_a(["f12","f13","f14"]); map ts_code → name via _infer_ts_code
# for each member: if ts in map: member["name_zh"] = map[ts]
# rewrite YAML preserving map_version/note; never add new ts_codes
```

- [x] **Step 5: Run patch once** (network) → check-in `stock_sw_l2.yaml`

```bash
python scripts/taxonomy/patch_stock_names.py \
  --in config/taxonomy/stock_sw_l2.yaml \
  --out config/taxonomy/stock_sw_l2.yaml
# assert: sampling lines contain name_zh; member count unchanged
```

If offline CI cannot patch: commit loader + fixture test; run patch in a follow-up commit when network available (still this plan Task 2).

- [x] **Step 6: pytest loader test PASS; Commit**

```bash
git add scripts/common/universe.py scripts/taxonomy/patch_stock_names.py \
  config/taxonomy/stock_sw_l2.yaml tests/test_universe_yaml_map.py
git commit -m "$(cat <<'EOF'
feat(taxonomy): pass through and patch stock name_zh

EOF
)"
```

---

### Task 3: `synthesize_l2_bars` (pure)

**Files:**
- Create: `scripts/metrics/l2_synth.py`
- Test: `tests/test_l2_synth.py`

**Interfaces:**
- Consumes: `normalize_weights` / `weight_raw` from `aggregate.py`
- Produces:

```python
def synthesize_l2_bars(
    member_bars_by_ts: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    trade_dates: Sequence[date],  # ascending; caller supplies (tests: explicit list)
) -> list[dict]:
    """Return OHLC records for replay_from_ohlc (skipped days omitted).
    Each record: trade_date, close_qfq, high_qfq, low_qfq, is_st=0, is_suspended=0.
    """
```

**Calendar (钉死):**

- `trade_dates` **必须是完整交易日序列**（生产：`trading_days_inclusive(start, D)`；测试：显式连续短列表）。
- 「上一交易日」= 该序列里 `t` 的前一个元素（注入列表 = 日历；**禁止** synth 内调全局 `prev_trade_date()` 以免挂网）。
- **禁止**把「有 bar 的日期并集」当作 `trade_dates`：缺中间日 close 时，并集会把 prev 跳到上一有 bar 日，把多日收益当成一日（与 spec 日历 prev 不符）。

- [x] **Step 1: Failing test — chain returns**

```python
def test_synth_chain_two_names_known_returns():
    from datetime import date
    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1 = date(2024, 1, 8), date(2024, 1, 9)
    bars = {
        "A.SZ": [
            {"trade_date": "2024-01-08", "close_qfq": 10.0, "high_qfq": 10.0, "low_qfq": 10.0,
             "float_mv": 1e9, "is_st": 0, "is_suspended": 0},
            {"trade_date": "2024-01-09", "close_qfq": 11.0, "high_qfq": 12.0, "low_qfq": 10.5,
             "float_mv": 1e9, "is_st": 0, "is_suspended": 0},
        ],
        "B.SZ": [
            {"trade_date": "2024-01-08", "close_qfq": 20.0, "high_qfq": 20.0, "low_qfq": 20.0,
             "float_mv": 1e9, "is_st": 0, "is_suspended": 0},
            {"trade_date": "2024-01-09", "close_qfq": 22.0, "high_qfq": 23.0, "low_qfq": 21.0,
             "float_mv": 1e9, "is_st": 0, "is_suspended": 0},
        ],
    }
    out = synthesize_l2_bars(bars, trade_dates=[d0, d1])
    # d0 has no prev in trade_dates → omit; d1 r=0.10 → P=1.10
    assert len(out) == 1
    assert out[0]["trade_date"] == "2024-01-09"
    assert abs(out[0]["close_qfq"] - 1.10) < 1e-9
```

- [x] **Step 2a: Missing mid-calendar close → omit (not jump prev)**

```python
def test_synth_omits_day_when_calendar_prev_close_missing():
    from datetime import date
    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1, d2 = date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)
    def bar(td, c):
        return {
            "trade_date": td, "close_qfq": c, "high_qfq": c, "low_qfq": c,
            "float_mv": 1e9, "is_st": 0, "is_suspended": 0,
        }
    # bars only on d0 and d2 — d1 is a trade day with no row
    bars = {"A.SZ": [bar("2024-01-08", 10.0), bar("2024-01-10", 12.0)]}
    out = synthesize_l2_bars(bars, trade_dates=[d0, d1, d2])
    # d2 prev=d1, no close on d1 → R empty → omit d2
    # Wrong bar-union trade_dates=[d0,d2] would use prev=d0 and emit P=1.2 — forbidden
    assert out == []
```

- [x] **Step 2b: ST day omitted; \(P_{\mathrm{prev}}\) survives gap**

```python
def test_synth_skips_st_day_and_chains_p_prev():
    from datetime import date
    from scripts.metrics.l2_synth import synthesize_l2_bars

    d0, d1, d2, d3 = (
        date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 11),
    )
    def bar(td, c, *, st=0):
        return {
            "trade_date": td, "close_qfq": c, "high_qfq": c, "low_qfq": c,
            "float_mv": 1e9, "is_st": st, "is_suspended": 0,
        }
    # d0→d1: +10% → first P=1.1; d2 all ST → omit; d3: +10% vs d2 close → P=1.1*1.1
    bars = {
        "A.SZ": [
            bar("2024-01-08", 10.0),
            bar("2024-01-09", 11.0),
            bar("2024-01-10", 11.0, st=1),
            bar("2024-01-11", 12.1),  # 12.1/11 - 1 = 0.1; chained P=1.21
        ],
    }
    out = synthesize_l2_bars(bars, trade_dates=[d0, d1, d2, d3])
    assert [r["trade_date"] for r in out] == ["2024-01-09", "2024-01-11"]
    assert abs(out[0]["close_qfq"] - 1.10) < 1e-9
    assert abs(out[1]["close_qfq"] - 1.21) < 1e-9  # not 1.10 (would be wrong first-P reset)
```

- [x] **Step 3: Implement `l2_synth.py`** per spec §3. Prev close date = prior entry in **full** `trade_dates`. \(P_{\mathrm{prev}}\), \(M^H_t\), clamp. Index bars by `(ts_code, iso_date)`.

- [x] **Step 4: PASS all synth tests; Commit**

```bash
git add scripts/metrics/l2_synth.py tests/test_l2_synth.py
git commit -m "$(cat <<'EOF'
feat(metrics): synthesize L2 OHLC from float_mv chain returns

EOF
)"
```

---

### Task 4: Wire L2 same-engine in `daily_run`

**Files:**
- Modify: `scripts/daily_run.py` (`replay_metrics_cross_section`)
- Create: `tests/test_c5_same_engine.py`, `tests/test_l2_daily_run_wire.py`
- Note: keep `aggregate_l1` import; remove L2 use of `aggregate_l2`

**Interfaces:**
- Produces: `l2_rows` with engine fields + `warm_to_hot_member_count` + `amount`
- Consumes: `synthesize_l2_bars`, `replay_from_ohlc`, `l2_members_map`, bars loader already in module

- [x] **Step 1: C5 failing test**

```python
def test_C5_same_engine_on_synthetic(tmp_path, monkeypatch):
    """Two identical OHLC members, equal float_mv → L2 asof T/R/tags/solar == single stock."""
    from tests.test_daily_run_metrics_wire import _short_params, _weekdays_ending, _seed_uptrend
    # or copy those helpers — MUST monkeypatch:
    monkeypatch.setattr(
        "scripts.daily_run.load_metrics_params", lambda: _short_params()
    )
    # METRICS_MIN_HISTORY alone does NOT cut vol_hist=252.
    # Seed bars.db via _seed_uptrend (or equivalent) for 000001.SZ and 000002.SZ identical
    # Monkeypatch l2_members_map → {"370100": ["000001.SZ", "000002.SZ"]}
    # dates = full weekday list covering the seed (not bar-union only)
    # Compare L2 asof T/right_side/tag_warm_to_hot/solar_term to replay_from_ohlc(000001)
```

- [x] **Step 2: Wire test — tag vs count (cool engine snap, not skip-day)**

```python
def test_l2_tag_not_or_of_members():
    # Unit-level _l2_asof_row only — do NOT pass snap=None here (that is skip-day → NULL).
    stock_rows = [
        {"ts_code": "A.SZ", "sw_l2_code": "370100", "tag_warm_to_hot": 0, "amount": 1e8},
        {"ts_code": "B.SZ", "sw_l2_code": "370100", "tag_warm_to_hot": 1, "amount": 2e8},
    ]
    cool_snap = {
        "T": "凉", "R": False, "tag_warm_to_hot": False, "tag_warm_to_flat": False,
        "solar_term": None,
    }
    row = _l2_asof_row(
        "370100", ["A.SZ", "B.SZ"], stock_rows, cool_snap,
        trade_date="2024-01-10", members_total=2,
    )
    assert row["tag_warm_to_hot"] == 0  # engine cool — not OR of members
    assert row["warm_to_hot_member_count"] == 1
```

If full process_day is heavy, extract:

```python
def _l2_asof_row(
    code: str,
    members: Sequence[str],
    stock_rows: Sequence[Mapping],
    snap: Mapping | None,  # asof snap from replay_from_ohlc, or None if skipped
    *,
    trade_date: str,
    members_total: int,
) -> dict: ...
```

- [x] **Step 3: Skip-day NULL test**

```python
def test_l2_skip_day_writes_null_engine_fields(...):
    row = _l2_asof_row(..., snap=None, stock_rows=[... tag=1 amount=1e8 ...])
    assert row["T"] is None and row["right_side"] is None
    assert row["tag_warm_to_hot"] is None  # not 0
    assert "tag_warm_to_hot" in row  # key present
    assert row["warm_to_hot_member_count"] == 1
```

- [x] **Step 4: Implement in `replay_metrics_cross_section`**

```python
# after stock_rows built:
from scripts.common.universe import l2_members_map
from scripts.metrics.l2_synth import synthesize_l2_bars
from scripts.common.calendar import trading_days_inclusive  # or dates ≤ D from bars

mapping = l2_members_map()
# cache: ts -> _load_symbol_bars(bconn, ts, D) for all members needed
# dates: MUST be trading_days_inclusive(start, D) (full calendar), never bar-date union.
#        Tests: monkeypatch trading_days_inclusive or inject list. No trade_dates() inside l2_synth.
l2_rows = []
for code, members in mapping.items():
    if not members:
        continue
    member_bars = {ts: cache[ts] for ts in members if ts in cache}
    synth = synthesize_l2_bars(member_bars, trade_dates=dates)
    snap = None
    if synth:
        snaps = replay_from_ohlc(params, synth, min_history=min_hist)
        asof = [s for s in snaps if s.get("trade_date") == td]
        snap = asof[-1] if asof else None
    # NEVER append snap.event_records to events
    l2_rows.append(_l2_asof_row(code, members, stock_rows, snap, trade_date=td,
                                members_total=len(members)))

# l1_rows unchanged via aggregate_l1(tradable_rows, td)
```

`_l2_asof_row` rules:
- From snap if present: `T`, `right_side`←`R`, tags, `solar_term`; `S_temp`/`RS`=None
- If snap None: those keys **explicitly None**
- `warm_to_hot_member_count` = count stock_rows with `sw_l2_code==code` and tag
- `amount` = sum non-null amounts for that `sw_l2_code`
- `members_tradable` = count stock_rows in members that are in tradable set (keep column meaningful)
- Do **not** use `_sql_int_bool` on nullable engine ints

- [x] **Step 5: Assert no L2 events** in a wire test (`events` only stock ts_codes)

- [x] **Step 6: PASS; Commit**

```bash
git add scripts/daily_run.py tests/test_c5_same_engine.py tests/test_l2_daily_run_wire.py
git commit -m "$(cat <<'EOF'
feat(daily_run): same-engine L2 rows; split member warm-to-hot count

EOF
)"
```

---

### Task 5: Issue digest headers, names, 亿元

**Files:**
- Modify: `scripts/issues/digest.py`
- Modify: `tests/test_l1_digest.py`

**Interfaces:**
- Produces: `_fmt_amount_yi(amount) -> str`; L2/stock tables with 名称 + 成交额(亿)
- Consumes: `load_l2_to_l1` / `load_stock_sw_l2` for name maps

- [x] **Step 1: Failing digest assertions**

```python
def test_l2_scan_headers_and_yi_and_names(tmp_path, monkeypatch):
    # seed daily_l2 370100 with amount=1.065e9, tag=0, warm_to_hot_member_count=1
    # + one L2 row with amount=None → 成交额 cell empty (not 0.000)
    body = render_l1_issue(...)
    assert "| T | 代码 | 名称 | RS | 右侧 | 节气 | 温转热 | 成分温转热 | 成交额(亿) |" in body
    assert "化学制药" in body
    assert "10.650" in body
    assert "1.065e+09" not in body
    assert "0.000" not in body  # NULL amount must not render as zero
```

```python
def test_stock_tables_keep_ts_code_add_name_column(...):
    assert "| ts_code | 名称 |" in body  # hot / right / exit
    # EXIT: ts_code | 名称 | event | T | detail
```

```python
def test_radar_hot_top_has_name_and_yi(...):
    body = render_radar_issue(...)
    assert "| ts_code | 名称 |" in body or "名称" in body.split("全市场温转热")[1][:200]
    assert "成交额(亿)" in body
```

- [x] **Step 2: Implement digest helpers**

```python
def _fmt_amount_yi(v: Any) -> str:
    if v is None:
        return ""
    return "%.3f" % (float(v) / 1e8)

def _stock_name_map() -> dict[str, str]:
    return {r["ts_code"]: (r.get("name_zh") or "") for r in load_stock_sw_l2()}

def _l2_name_map() -> dict[str, str]:
    return {r["code"]: (r.get("name_zh") or "") for r in load_l2_to_l1()}
```

L2 SELECT add `warm_to_hot_member_count`, `amount`. Display row →  
`(T, code, name, RS, right_side, solar_term, tag_warm_to_hot, member_count, _fmt_amount_yi(amount))`.

**Must** rewrite `_sort_l2_key` to match the new SELECT tuple indices (today it assumes `code,T,S_temp,...`; after change sort on `T` then `S_temp` still — read by name/index carefully).

Stock hot/right/radar: insert name after `ts_code`; last col `_fmt_amount_yi`.  
Exit table: insert name after `ts_code`.

Do **not** change `_fmt_cell` float `%.4g` globally.

Issue L2 code list stays `_l2_codes_for_l1` = DISTINCT `daily_stock.sw_l2_code` (unchanged; YAML-only empty L2s need not appear on Issue).

- [x] **Step 3: Update `_seed` in tests** with new L2 cols; fix assertions for new headers

- [x] **Step 4: PASS; Commit**

```bash
git add scripts/issues/digest.py tests/test_l1_digest.py
git commit -m "$(cat <<'EOF'
feat(issues): L2/stock name columns and amount in 亿元

EOF
)"
```

---

### Task 6: Done-when docs

**Files:** `README.md`, `todo.md`, spec status line

- [x] Mark todo.md §0 items done / point to this plan
- [x] Spec status → `已落地；plan 见 2026-10-06-l2-same-engine-digest.md`
- [x] README one-liner: L2 same-engine + digest names/亿元
- [x] `pytest tests/test_daily_l2_cols.py tests/test_l2_synth.py tests/test_c5_same_engine.py tests/test_l2_daily_run_wire.py tests/test_l1_digest.py tests/test_universe_yaml_map.py -q`
- [x] Full `pytest tests/ -q` offline green
- [x] Commit docs only

```bash
git add README.md todo.md docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md
git commit -m "$(cat <<'EOF'
docs: mark L2 same-engine digest slice ready for ship

EOF
)"
```

## Out of this plan

- L1 same-engine C5
- Unmapped 全A, YAML daily fetch, RS/Spearman, board_calc, holiday asof/limit, L2 signal_event, mv-weighted density share

## Done when

1. C5 synthetic twins match single-name engine at asof  
2. Cool L2 + one hot member → industry tag 0, member count 1  
3. Skip-day asof → engine SQL NULL keys present; count/amount from cross-section  
4. Digest: code+名称; 亿元 3dp; no scientific amount on those cells  
5. `load_stock_sw_l2` exposes `name_zh`; production YAML patched (or follow-up network commit called out)  
6. Offline pytest green; L1 still interim  

---

## Plan self-review

| Spec § | Task |
|--------|------|
| §2.1 split tag / count | T4 |
| §2.2 names + loader + no dump_yaml | T2, T5 |
| §2.3 亿元 | T5 |
| §3 synth formula / calendar / P_prev / skip | T3, T4 |
| §4 schema + COLS + not INT_BOOL | T1 |
| §5 headers supersede ops | T5 |
| §7 tests 1–6 | T1–T5 |
| §8 non-goals | Global Constraints / Out |

No TBD placeholders. Types: `synthesize_l2_bars` → `list[dict]` OHLC; `_l2_asof_row` → `dict` for upsert.

### Plan CR follow-up

| Finding | Verdict | Action |
|---------|---------|--------|
| Step 2 `...` placeholder | **真** | Full fixtures |
| Global calendar inside synth | **真** | Injected `trade_dates` only |
| C5 only `METRICS_MIN_HISTORY` | **真** | `_short_params` + seed skeleton |
| bar-union ≡ full calendar | **真洞**（先前误判） | Forbid bar-union; add missing-mid-close test |
| Step 2 no real \(P_{\mathrm{prev}}\) chain | **真** | d0→d1 success, skip d2, d3 → 1.21 |
| tag_not_or with `snap=None` | **真** | Cool snap + count=1; NULL only in skip test |
| amount NULL → empty / Radar headers | **真 nit** | Digest asserts added |
| `_sort_l2_key` index drift | **真 nit** | Rewrite in Task 5 |
| Issue list YAML-empty L2s | **假** | Unchanged |

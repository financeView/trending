# Spec G：Digest / Radar 可读性 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make L1/L2 Issue tables show state vs event in plain language (是/否 + 「今日…」), add `成分热以上`, and make Radar L1 temperature read `daily_l1.T` instead of stock-max `T*`.

**Architecture:** Render-only changes in `scripts/issues/digest.py`. Booleans go through `_fmt_yn`; hot-plus counts are SQL aggregates at render time; Radar drops `_hottest_t` for the per-L1 temperature cell.

**Tech Stack:** Python 3.11; sqlite3; pytest; existing `upsert_daily_*` test helpers.

**Spec:** [`docs/superpowers/specs/2026-10-10-digest-radar-ux-design.md`](../specs/2026-10-10-digest-radar-ux-design.md)

## Global Constraints

- Do not change metrics / FSM / `daily_*` write path or schema.
- Do not change Spec F workflow files.
- Boolean cells: `是` / `否` only — never `0` / `1` for `在右侧` / `今日温转热`.
- `成分热以上` = `T IN ('热','沸')` only (exclude `温`).
- Radar `T` = `daily_l1.T`; forbid stock-max for that column.
- L1 `成分热以上` filters `daily_stock.l1_id` (not YAML closure).
- Exclude committing `data/trend.db` / heartbeat / cache unless user explicitly asks.

---

## File map

| File | Role |
|------|------|
| `scripts/issues/digest.py` | `_fmt_yn`, hot-plus count, header/footnote/Radar T |
| `tests/test_l1_digest.py` | Header + yn + Radar T fixture assertions |
| `tests/test_digest_rs_vol.py` | Header string updates (量列 scope unchanged) |
| `tests/test_digest_hot_plus.py` (new, optional if folded into test_l1_digest) | 成分热以上 count + yn |

Prefer extending `tests/test_l1_digest.py` + `tests/test_digest_rs_vol.py` unless a new file stays clearer for hot-plus.

---

### Task 1: `_fmt_yn` + L1/L2/个股布尔列与表头

**Files:**
- Modify: `scripts/issues/digest.py`
- Modify: `tests/test_l1_digest.py`
- Modify: `tests/test_digest_rs_vol.py`

**Interfaces:**
- Produces: `_fmt_yn(v: Any) -> str` — `1/true/"1"`→`是`; `0/false/"0"`→`否`; else `""`

- [ ] **Step 1: Write failing tests for headers + 是/否**

In `tests/test_l1_digest.py`, replace old header asserts with:

```python
L1_SELF_HEADER = (
    "| T | l1_id | 名称 | RS | 量 | 在右侧 | 节气 | 今日温转热 | "
    "今日成分温转热 | 成分热以上 | 成交额(亿) |"
)
L2_HEADER = (
    "| T | 代码 | 名称 | RS | 量 | 在右侧 | 节气 | 今日温转热 | "
    "今日成分温转热 | 成分热以上 | 成交额(亿) |"
)
```

Assert `_seed_with_daily_l1` render contains `L1_SELF_HEADER`, and a row with `right_side=1` shows `| 是 |` in the 在右侧 position (not bare `| 1 |` as that cell).  
Assert「今日温转热（个股」table header uses `在右侧` and values 是/否.

Update `tests/test_digest_rs_vol.py` header strings the same way (成分热以上 column present; 量 still on L1/L2 only).

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/pytest tests/test_l1_digest.py tests/test_digest_rs_vol.py -q
```

Expected: FAIL on old headers / missing 是.

- [ ] **Step 3: Implement helpers + wire L1/L2/个股布尔**

```python
def _fmt_yn(v: Any) -> str:
    if v is None:
        return ""
    if v is True or v == 1 or v == "1":
        return "是"
    if v is False or v == 0 or v == "0":
        return "否"
    return ""
```

Update `render_l1_issue` headers/cells per spec §4.1 / §4.3. For this task, **`成分热以上` may temporarily render `0`** for every row (Task 2 fills real counts) so headers/yn tests can pass.

Add footnote after L2「量」注 (spec §4.1 text).

- [ ] **Step 4: Run — expect PASS** (headers/yn; hot-plus may still be 0)

```bash
.venv/bin/pytest tests/test_l1_digest.py tests/test_digest_rs_vol.py -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/issues/digest.py tests/test_l1_digest.py tests/test_digest_rs_vol.py
git commit -m "$(cat <<'EOF'
feat(digest): show 在右侧/今日温转热 as 是/否

EOF
)"
```

---

### Task 2: `成分热以上` 计数

**Files:**
- Modify: `scripts/issues/digest.py`
- Modify: `tests/test_l1_digest.py` (or new `tests/test_digest_hot_plus.py`)

**Interfaces:**
- Produces: `_count_members_hot_plus(conn, trade_date, *, l1_id=None, sw_l2_code=None) -> int`
- Exactly one of `l1_id` / `sw_l2_code` must be set (assert or ignore the other).

- [ ] **Step 1: Failing test**

Seed three stocks under one L2 / L1: `T=热`, `T=沸`, `T=温` (and optionally `凉`).  
Render L1 issue; assert L2 row `成分热以上` cell is `2`; L1 自身 row is `2` (same three mapped via `l1_id`).

```python
def test_member_hot_plus_excludes_warm(tmp_path, monkeypatch):
    ...
    assert "| 2 |" in l2_row_or_parse_成分热以上_cell
```

Prefer parsing the markdown row over brittle full-line match.

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/pytest tests/test_l1_digest.py::test_member_hot_plus_excludes_warm -q
```

- [ ] **Step 3: Implement SQL count + wire into L1/L2 cells**

```sql
SELECT COUNT(*) FROM daily_stock
WHERE trade_date=? AND T IN ('热','沸') AND sw_l2_code=?
-- or AND l1_id=?
```

- [ ] **Step 4: Run digest tests — PASS**

```bash
.venv/bin/pytest tests/test_l1_digest.py tests/test_digest_rs_vol.py -q
```

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(digest): add 成分热以上 member count column

EOF
)"
```

---

### Task 3: Radar `T` ← `daily_l1.T` + 表头/总览文案

**Files:**
- Modify: `scripts/issues/digest.py` (`render_radar_issue`)
- Modify: `tests/test_l1_digest.py` (`test_radar_stock_warm_header_and_footnote` + new case)

**Interfaces:**
- Consumes: `daily_l1` row for `(trade_date, code=l1_id)`
- Stops using `_hottest_t` inside Radar L1 loop (delete helper if unused)

- [ ] **Step 1: Failing tests**

```python
RADAR_L1_HEADER = (
    "| L1 | l1_id | T | 个股 | 右侧个股 | 右侧占比 | 今日个股温转热 |"
)

def test_radar_t_uses_daily_l1_not_stock_max(tmp_path, monkeypatch):
    # daily_l1.T = 凉; daily_stock under that l1 includes T=沸
    md = render_radar_issue(...)
    assert RADAR_L1_HEADER in md
    assert "T*" not in md
    # row for that l1 shows 凉, not 沸 as the T cell
    assert "今日温转热=" in md.split("## 总览")[1]  # 总览文案
    assert "右侧个股=" in md
```

Update footnote asserts to new spec §4.4 text (contains `daily_l1` / `同引擎`).

- [ ] **Step 2: Run — expect FAIL**

```bash
.venv/bin/pytest tests/test_l1_digest.py::test_radar_t_uses_daily_l1_not_stock_max tests/test_l1_digest.py::test_radar_stock_warm_header_and_footnote -q
```

- [ ] **Step 3: Implement**

Per L1 bucket:

```python
l1_t_row = conn.execute(
    "SELECT T FROM daily_l1 WHERE trade_date=? AND code=?",
    (td, b.l1_id),
).fetchone()
t = l1_t_row[0] if l1_t_row else None
# keep stock aggregates for counts only — do not derive t from stocks
```

Update headers, 总览 line, footnote. Remove `_hottest_t` if unused.

- [ ] **Step 4: Full digest suite**

```bash
.venv/bin/pytest tests/test_l1_digest.py tests/test_digest_rs_vol.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(radar): use daily_l1.T instead of stock-max T*

EOF
)"
```

---

### Task 4: 收尾核对

- [ ] **Step 1: Grep 旧文案**

```bash
rg -n "T\*|成分温转热|个股温转热|_hottest_t" scripts/issues/digest.py tests/test_l1_digest.py tests/test_digest_rs_vol.py
```

Expected: no production `T*` / old L1·L2 headers; tests only mention old strings if asserting absence.

- [ ] **Step 2: Broader regression (optional but recommended)**

```bash
.venv/bin/pytest tests/test_l1_digest.py tests/test_digest_rs_vol.py tests/test_signal_event_persist.py -q
```

- [ ] **Step 3: Mark spec status**

In spec header: `状态：设计中` → `状态：已落地（plan 执行完）` or leave for implementer after merge.

- [ ] **Step 4: Final commit if spec status / todo touched**

```bash
git commit -m "$(cat <<'EOF'
docs(spec-g): mark digest/radar UX landed

EOF
)"
```

---

## Self-review checklist

- [x] Spec §4.1–4.5 covered by Tasks 1–3  
- [x] TDD order per task  
- [x] No workflow / metrics schema scope creep  
- [x] Radar T fixture proves 凉 beats stock 沸  
- [x] 成分热以上 excludes 温  

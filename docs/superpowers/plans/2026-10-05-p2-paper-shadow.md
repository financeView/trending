# P2 Paper Book + Live Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship shared execution (`fill_day`) for track L (`live_shadow_step` → immutable `paper_fill` + `shadow_book_state` in `trend.db`) and a **synthetic/audit** H CLI; wire L after `run_meta=ok`. Causal frozen-param H (spec default) is **not** this slice.

**Architecture:** Pure `fill_day(T, prev_day_signals, book, bars_T, costs)` mutates an in-memory book and emits fill rows. L consumes **active** `signal_event` ids on `prev_trade_date(T)` only when `run_meta(T)=ok`; if confirm-day `run_meta` **exists** and `status≠ok`, skip L (missing confirm row is allowed). **`--from-heartbeat` walks every `heartbeat.days` entry** (catch-up prefix), not only `days[-1]`. If T has no candidate with `open_raw`+`limit_*` → **skip the day with no inserts** (do not `data_gap`-consume; catch-up often lacks limits). Per-name `data_gap` only when the day actually ran. Append-only fills; L consumption is `track='L'` terminal `(signal_event_id, side)`; same `(id, side, fill_date)` is not inserted twice; later `fill_date` allowed for `unfilled_sell` retries. Book + fills share **one SQLite `commit`**. `intent_date=next_trade_date(signal_date)` even if the fill retries later. L `param_version`/`map_version` from **confirm-day** `run_meta` when present. Audit H **must not** write `paper_fill` rows that L would consume (`output/eval/{run_id}/` or in-memory only).

**Tech Stack:** Python 3.11, sqlite3, PyYAML, pytest, GitHub Actions.

## Global Constraints

- Spec: [`2026-09-30-backtest-eval-design.md`](../specs/2026-09-30-backtest-eval-design.md) §4.0–4.7 / §4.10–4.11 · ops live_shadow only if `run_meta=ok`
- D+1 = **trade-day** via `scripts/common/calendar.py` `next_trade_date` / `prev_trade_date`
- Fill px = `open_raw` ± impact bp; costs from `config/eval/costs.yaml` only (no env override)
- Limits vs `open_raw` (never qfq); missing `limit_*` or `open_raw` on a **running** day → `data_gap`; **empty/unusable T bars → skip L**
- `intent_date` = `next_trade_date(signal_date)` (not retry `fill_date`)
- Buy only `ENTER_RIGHT` events (never `tag_warm_to_hot` alone); sell `EXIT_RIGHT`
- Same-day: pending sells → due sells → buys (RS desc, `ts_code` asc)
- `rule_id=mvp_right_side_v1`
- `paper_fill` immutable: no UPDATE/DELETE of existing rows; L does not rewrite fills on event supersede
- L1/L2 baskets are **not** booked
- **Out of this plan:** §4.8 walk-forward / vs_random / vs_hs300; causal H recompute; same-engine L2; full-A sync; SW YAML (next plan); `live_shadow/` snip files

## Sequence after P2

1. This plan (engine + L hook + audit H)
2. SW2021→L1 YAML + stock map (replace stub 5 / in-code `STUB_*`)
3. Defer: same-engine C5, full-A bars sync
4. Replay **2026-09-30** on the YAML universe (sync those members + `daily_run`). Prefer **catch-up `D < session asof`** (or bars that already have `limit_*`). Fake asof + skip EM → `partial` → L will skip. Not 全A, not two-year WF.

## File map

| Path | Responsibility |
|------|----------------|
| `config/eval/costs.yaml` | Already present (`cost_version: v1`) |
| `scripts/eval/costs.py` | Load frozen dataclass |
| `scripts/eval/book.py` | `BookState` / `Position` / MTM |
| `scripts/eval/fill_day.py` | Shared `fill_day` + `round_kpis` |
| `scripts/eval/paper_book.py` | **Audit/synthetic** H window CLI (in-memory / files under `output/eval/{run_id}/`; **not** L `paper_fill`) |
| `scripts/eval/live_shadow_step.py` | Track L: walk heartbeat days; skip unusable bars |
| `scripts/eval/shadow_store.py` | Load/save `shadow_book_state` in trend.db |
| `scripts/common/db.py` | `insert_paper_fills` append-only; L-only consume; `shadow_book_state` |
| `.github/workflows/daily-trend.yml` | L **before** the single db commit, only if ok |
| `tests/test_fill_day.py` | Named fixtures §4.11 + intent_date + detail JSON |
| `tests/test_live_shadow_gate.py` | skip unless ok; missing confirm allowed; catch-up walk; missing bars |

---

### Task 1: Costs + book state

**Files:** `scripts/eval/costs.py`, `book.py`; Test `tests/test_eval_costs_book.py`

- [x] Load `config/eval/costs.yaml` → frozen `EvalCosts`
- [x] `BookState`; `mtm`
- [x] Commit

### Task 2: `fill_day` + named fixtures

**Files:** `scripts/eval/fill_day.py`; Test `tests/test_fill_day.py`

- [x] `fill_fri_enter_mon_buy` — assert `next_trade_date(Fri)==Mon`, then Mon open buy
- [x] `fill_enter_right_only` — WARM_TO_HOT only → no buy
- [x] `fill_forced_exit_st` — held + EXIT forced_exit_untradable → next session sell
- [x] `fill_open_end_kpi` — `round_kpis`: `n_open_end≥1`, `win_rate is None`
- [x] missing limits → `data_gap`; `rule_id=mvp_right_side_v1`
- [x] Commit

### Task 3: Persist `paper_fill` (append-only)

**Files:** `scripts/common/db.py`; Test `tests/test_paper_fill_persist.py`

- [x] `insert_paper_fills` skip duplicate `fill_id`
- [x] Consumed = L-track terminal `(signal_event_id, side)`
- [x] Skip duplicate `(signal_event_id, side, fill_date)`; later date ok for pending retry
- [x] `shadow_book_state` table + roundtrip
- [x] Commit

### Task 4: `live_shadow_step` CLI

**Files:** `scripts/eval/live_shadow_step.py`

- [x] skip heartbeat skip / `run_meta(T)≠ok` / confirm **row exists and ≠ok**
- [x] Book in `trend.db.shadow_book_state` (not a sidecar JSON)
- [x] Confirm-day param/map versions on fills
- [x] `--from-heartbeat` walks `heartbeat.days` in order; skip T with unusable bars (no consume)
- [x] fills + book one SQLite commit
- [x] Second run same asof: no new consumed ids
- [x] Commit

### Task 5: `paper_book` CLI (audit H)

**Files:** Create `scripts/eval/paper_book.py`; Test `tests/test_paper_book.py`

- [x] `--from --to` walk **`trading_days_inclusive` / `next_trade_date`**, not civil days
- [x] Tests use **in-memory** signals. Do **not** insert audit rows into `trend.db.paper_fill` (would consume L ids). Persist H under `output/eval/{run_id}/` if a file is needed.
- [x] Summary: accumulate **all** window fills + final book. Pair closed rounds by position FIFO, not “first buy of ticker”. `n_open_end` / `win_rate` via `window_kpis` — **not** WF gates.
- [x] Commit

### Task 6: Actions wire + README

**Files:** Modify `.github/workflows/daily-trend.yml`, `README.md`

**Only this order:** `daily_run` → `live_shadow_step --from-heartbeat` (walks processed days; each day no-ops unless T ok **and** bars usable) → **one** `git add data/trend.db data/heartbeat.json` → Issues (`continue-on-error`)

Do not call L once on `days[-1]` only. Catch-up days without `limit_*` skip (events stay unconsumed until a later T that is that intent date — they will not be filled on a later asof).

- [x] Patch workflow; README P2 commands
- [x] Commit

### Task 7: Done-when

- [x] `pytest tests/ -q` includes fill fixtures + L gate + persist + paper_book + workflow order
- [ ] Manual: dry-run L against current `trend.db` (may skip: last asof `partial`)
- [x] Commit plan checkboxes

## Out of P2

- Walk-forward §4.8, vs_random, vs_hs300 as hard gates
- Causal H (frozen param replay of OHLC → events → fill)
- `limit_up_unfillable`, `board_calc_v1`
- Real-money track M
- `output/eval/live_shadow/` snip
- SW YAML / full-A (next)

## Done when

1. Four named fill fixtures green (calendar + open-end KPI)
2. L skips `status≠ok`; append-only; book survives via `trend.db`
3. Audit H can replay a synthetic Fri–Mon **trade-day** window
4. Actions: L only on ok days; Issues cannot drop the db commit
5. **不要求** WF 两年门禁 / 因果 H / 9.30 在假 asof 上变 ok

# trending

A-share trend metrics / ops / paper eval (specs under `docs/superpowers/specs/`).

## Local loop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
# offline metrics wire (stub coverage stats only):
python scripts/daily_run.py --asof 2024-01-10 --force-trade-day --offline-calendar --stub-coverage
```

Mapped-universe sync (Git `stock_sw_l2.yaml`), then **real** coverage:

```bash
python scripts/sync_bars_sample.py --end 2026-09-30
python scripts/daily_run.py --date 2026-09-30 --only-date
```

`--date D` is replay **start**, not session asof (`latest_trade_day()` unless `--asof`). `--only-date` requires `--date`.

Actions `workflow_dispatch`:

| 模式 | inputs | daily_run |
|------|--------|-----------|
| cron / 日更 | 不填 date | 无 `--date` |
| 单日补洞 | date=D, only_date=true | `--date D --only-date` |
| 从 D 追赶 | date=D | `--date D` |

Workflow is two jobs (`sync` → `metrics`). Incomplete sync (`sync_complete=false`) skips the metrics job (daily_run / shadow / trend.db commit / Issues) and emits `::warning::sync_incomplete`. Spec F removed `run_deferred` and production `--time-budget-min` truncation.

## P1 L1 / Radar Issues

```bash
# dry-run markdown (14 L1 + radar) from trend.db
python scripts/issues/update_l1_issues.py --date 2024-01-10 --dry-run --out-dir output/issues
# live upsert (needs GITHUB_TOKEN + GITHUB_REPOSITORY)
python scripts/issues/update_l1_issues.py --date 2024-01-10 --live
```

- Plans: `docs/superpowers/plans/2026-10-01-p0-daily-pipeline.md`, `2026-10-01-p05-metrics-fsm.md`, `2026-10-04-p1-l1-issues-radar.md`
- Data contract: `docs/superpowers/specs/2026-10-01-market-data-contract-design.md`
- Actions (cron 北京 19:00): sync **mapped SW YAML** universe → `daily_run` (no `--stub-coverage`) → `live_shadow_step --from-heartbeat` → **one** commit of `trend.db`+heartbeat → L1/Radar Issues (`continue-on-error`). Coverage denominator includes `mapped_sync_coverage` over the mapped set.

## P2 paper / live shadow

```bash
# Track L one asof (skip if run_meta≠ok or bars unusable)
python scripts/eval/live_shadow_step.py --asof 2024-01-08 --dry-run
python scripts/eval/live_shadow_step.py --from-heartbeat
# Audit H window (in-memory/file signals; does not write paper_fill)
python scripts/eval/paper_book.py --from 2024-01-05 --to 2024-01-08 \
  --signals-json /tmp/signals.json --out output/eval --run-id audit-fri-mon
```

**L2 same-engine (shipped):** synthetic float_mv chain OHLC → same FSM as stocks; industry `tag_warm_to_hot` split from `warm_to_hot_member_count`; Issue digests add 名称 columns and 成交额(亿) (3dp).

**L1 same-engine (shipped):** L1 member-closure synth → same FSM as stocks/L2; L1 `tag_warm_to_hot` split from `warm_to_hot_member_count`; digest `## L1 自身` + Radar 个股温转热表头对齐 Spec B.

**RS / S_temp / VOL (shipped):** pure-price RS (peer percentile, `local_*` isolation); §5.4 `S_temp` + C1 allowlist; Spearman gold+synthetic gate (live asof waived); stock `VOL_score` bypass (turnover window percentile); L2/L1 `VOL_score` SQL null; digest sort RS → VOL → amount +「量」列。

**Ops A (shipped):** asof limit soft-ok (`ok`+warn, `last_ok` advances); nested heartbeat readers; Actions `only_date` pins `live_shadow --asof`.

**Still out of ship:** tree-out bars warmup (deferred), causal H / walk-forward gates, L2/L1 replay perf / `engine_state`, basket non-null VOL.

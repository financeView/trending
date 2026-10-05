# trending

A-share trend metrics / ops / paper eval (specs under `docs/superpowers/specs/`).

## Local loop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
# offline metrics wire (stub coverage stats only):
python scripts/daily_run.py --date 2024-01-10 --force-trade-day --offline-calendar --stub-coverage
```

Network sync of classification-universe stub, then **real** coverage:

```bash
python scripts/sync_bars_sample.py \
  --from-universe config/taxonomy/universe_stub.yaml \
  --end 2024-01-10 --with-limits
python scripts/daily_run.py --date 2024-01-10 --force-trade-day --offline-calendar
```

## P1 L1 / Radar Issues

```bash
# dry-run markdown (14 L1 + radar) from trend.db
python scripts/issues/update_l1_issues.py --date 2024-01-10 --dry-run --out-dir output/issues
# live upsert (needs GITHUB_TOKEN + GITHUB_REPOSITORY)
python scripts/issues/update_l1_issues.py --date 2024-01-10 --live
```

- Plans: `docs/superpowers/plans/2026-10-01-p0-daily-pipeline.md`, `2026-10-01-p05-metrics-fsm.md`, `2026-10-04-p1-l1-issues-radar.md`
- Data contract: `docs/superpowers/specs/2026-10-01-market-data-contract-design.md`
- Actions (cron 北京 19:00): sync stub universe → `daily_run` (no `--stub-coverage`) → `live_shadow_step --from-heartbeat` (no-op unless `run_meta=ok` and bars usable) → **one** commit of `trend.db`+heartbeat → L1/Radar Issues (`continue-on-error`). Coverage U is the stub member set, not full A-share.

## P2 paper / live shadow

```bash
# Track L one asof (skip if run_meta≠ok or bars unusable)
python scripts/eval/live_shadow_step.py --asof 2024-01-08 --dry-run
python scripts/eval/live_shadow_step.py --from-heartbeat
# Audit H window (in-memory/file signals; does not write paper_fill)
python scripts/eval/paper_book.py --from 2024-01-05 --to 2024-01-08 \
  --signals-json /tmp/signals.json --out output/eval --run-id audit-fri-mon
```

**Still out of ship:** full SW2021 YAML / full-A sync, same-engine L2/L1 (§10 C5), causal H / walk-forward gates, Spearman / `test_C1`.
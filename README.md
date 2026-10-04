# trending

A-share trend metrics / ops / paper eval (specs under `docs/superpowers/specs/`).

## Public-fund holdings by industry

A separate quarterly workflow snapshots CNINFO public-fund stock holdings across the repository's SW2021 L2 → custom L1 taxonomy; manual runs accept a validated L1/L2 pair. GitHub scheduled workflows only run from the default branch, so the cron remains dormant while this feature is confined to its independent branch. See [`docs/fund-industry-holdings.md`](docs/fund-industry-holdings.md) for source coverage, denominator, limitations, and run instructions. Workflow: `.github/workflows/fund-industry-holdings.yml`.

## P0 / P0.5 data wiring

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
python scripts/daily_run.py --date 2024-01-10 --force-trade-day --offline-calendar --stub-coverage
```

Optional network sample sync (sina OHLC + BaoStock flags; EM limits optional):

```bash
python scripts/sync_bars_sample.py --codes 000001.SZ,600519.SH --end 2024-01-10
python scripts/sync_bars_sample.py --codes 000001.SZ,600519.SH --end 2024-01-10 --with-limits
# then real coverage (no --stub-coverage):
python scripts/daily_run.py --date 2024-01-10 --force-trade-day --offline-calendar
```

- Plan: `docs/superpowers/plans/2026-10-01-p0-daily-pipeline.md`
- P0.5 metrics FSM: `docs/superpowers/plans/2026-10-01-p05-metrics-fsm.md`
- Data contract: `docs/superpowers/specs/2026-10-01-market-data-contract-design.md`
- Actions: `.github/workflows/daily-trend.yml` (cron 北京 19:00). `--stub-coverage` only skips coverage **stats** (keeps CI green); metrics replay still runs when bars exist. Turn stub off in Actions only after **full-universe sync** is in the workflow (not a P0.5 code blocker).

**Daily-trend P0.5 follow-ups (separate from fund holdings):** L1 Issues / radar digests, `paper_book` / `live_shadow` consumption, the full-universe mapping for daily metrics, and Spearman / `test_C1` remain **not** hard gates for that pipeline. The SW2021 tree above is used by the fund-holdings workflow only.

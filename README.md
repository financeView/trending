# trending

A-share trend metrics / ops / paper eval (specs under `docs/superpowers/specs/`).

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
- Data contract: `docs/superpowers/specs/2026-10-01-market-data-contract-design.md`
- Actions: `.github/workflows/daily-trend.yml` (cron 北京 19:00; uses `--stub-coverage` until full sync)

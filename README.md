# trending

A-share trend metrics / ops / paper eval (specs under `docs/superpowers/specs/`).

## P0 (in progress)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
python scripts/daily_run.py --date 2024-01-10 --force-trade-day --offline-calendar
```

- Plan: `docs/superpowers/plans/2026-10-01-p0-daily-pipeline.md`
- Data contract: `docs/superpowers/specs/2026-10-01-market-data-contract-design.md`
- Actions: `.github/workflows/daily-trend.yml` (cron 北京 19:00)

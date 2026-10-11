# Hard-freeze stamp runbook (Protocol B)

1. Change `hard_freeze_min_suspend_days` and/or bump `param_version` in `config/metrics/a_share_daily.yaml`.
2. Run a **full sync** on the target `bars.db` (Actions sync job or local `scripts/sync_bars_sample.py`) so hard_freeze pass rewrites flags and UPSERTs `hard_freeze_pass_meta`. Success end writes `data/cache/sync_status.json` with `sync_complete` and `session_asof`.
3. Verify: `python scripts/check_hard_freeze_stamp.py` (exit 0) or inspect the stamp row.
4. Then run metrics / `daily_run` / eval.
5. Paper/offline eval: green a stamped `daily_run` first (`paper_book` is not gated).
6. Actions: after hard_freeze failure, start a **new** workflow run to refresh stamp under a new `bars-${{run_id}}`. Do not rely on Re-run failed jobs to overwrite an existing cache key.

## live_shadow sync_status gate

`live_shadow_step.run_asof` hard-fails before `fill_day` unless `data/cache/sync_status.json` has `sync_complete=true` and `session_asof >=` the fill day `T` (Spec F catch-up: tip covers earlier `T`). Incomplete sync, hard_freeze fail, missing file, or a stale tip (`session_asof < T`) → exit 1; calendar / missing_bars skips still exit 0. Re-run a **full** sync so the tip covers the shadow day before claiming fills. Debug-only: `TRENDING_ALLOW_INCOMPLETE_FILL=1` (never for CI).

## limit_rule rollback (vendor_fields)

Production `costs.yaml` stays `board_calc_v1` so this gate is idle. Before switching to `vendor_fields`, clear residual calculated limits on the **same** `bars.db` used for fill (whole DB; no date window), then bump `cost_version`:

```sql
UPDATE bars
SET limit_up=NULL, limit_down=NULL, limit_source=NULL
WHERE limit_source='board_calc_v1';
```

Check: `python scripts/check_limit_rule_bars.py --bars-db PATH --limit-rule vendor_fields` (exit 0). Leaving residue → `live_shadow` exit 1.

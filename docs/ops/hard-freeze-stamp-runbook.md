# Hard-freeze stamp runbook (Protocol B)

1. Change `hard_freeze_min_suspend_days` and/or bump `param_version` in `config/metrics/a_share_daily.yaml`.
2. Run a **full sync** on the target `bars.db` (Actions sync job or local `scripts/sync_bars_sample.py`) so hard_freeze pass rewrites flags and UPSERTs `hard_freeze_pass_meta`.
3. Verify: `python scripts/check_hard_freeze_stamp.py` (exit 0) or inspect the stamp row.
4. Then run metrics / `daily_run` / eval.
5. Paper/offline eval: green a stamped `daily_run` first (`paper_book` is not gated).
6. Actions: after hard_freeze failure, start a **new** workflow run to refresh stamp under a new `bars-${{run_id}}`. Do not rely on Re-run failed jobs to overwrite an existing cache key.

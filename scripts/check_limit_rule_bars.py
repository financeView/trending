"""CLI: exit 0 if bars ok for limit_rule; else non-zero (limit_rule rollback Spec)."""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.common.bars import DEFAULT_BARS_DB
from scripts.eval.costs import load_costs
from scripts.eval.limit_rule_guard import check_limit_rule_bars


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bars-db", default="", help="bars.db path (default cache)")
    p.add_argument(
        "--limit-rule",
        default="",
        help="override costs.limit_rule (default: load_costs())",
    )
    args = p.parse_args(argv)
    rule = args.limit_rule or load_costs().limit_rule
    path = args.bars_db or DEFAULT_BARS_DB
    return check_limit_rule_bars(path, rule)


if __name__ == "__main__":
    raise SystemExit(main())

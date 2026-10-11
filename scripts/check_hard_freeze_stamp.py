"""CLI: exit 0 if hard_freeze stamp matches yaml; else non-zero."""
from __future__ import annotations

import argparse

from scripts.common.hard_freeze import check_hard_freeze_stamp


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bars-db", default="", help="bars.db path (default cache)")
    args = p.parse_args(argv)
    return check_hard_freeze_stamp(args.bars_db or None)


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the quarterly public-fund industry holdings aggregation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.fund_industry import (
    aggregate_all_report,
    aggregate_report,
    build_classification_asof,
    fetch_latest_report,
    fetch_sw_classification_history,
    load_taxonomy,
    render_markdown,
    resolve_l1,
    resolve_l2,
    write_report_files,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate latest CNINFO public-fund stock holdings using this repository's SW2021 industry tree."
    )
    parser.add_argument("--industry-l1", default="", help="repository L1 id/name; required together with --industry-l2")
    parser.add_argument("--industry-l2", default="", help="exact SW2021 L2 code or name, e.g. 370100 or 化学制药")
    parser.add_argument("--all-industries", action="store_true", help="aggregate the complete 14/134 taxonomy for scheduled runs")
    parser.add_argument("--report-date", default="", help="optional report date YYYYMMDD; blank selects the newest published quarter")
    parser.add_argument("--output-dir", default="reports/fund-industry", help="aggregate report output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        has_l1 = bool(args.industry_l1.strip())
        has_l2 = bool(args.industry_l2.strip())
        if args.all_industries and (has_l1 or has_l2):
            raise ValueError("--all-industries cannot be combined with an L1/L2 selection")
        if not args.all_industries and has_l1 != has_l2:
            raise ValueError("industry-l1 and industry-l2 must be provided together")
        if not args.all_industries and not has_l1:
            raise ValueError("provide both industry-l1 and industry-l2, or use --all-industries")

        taxonomy = load_taxonomy()
        if args.all_industries:
            selection = None
        else:
            l1 = resolve_l1(args.industry_l1, taxonomy)
            l2 = resolve_l2(args.industry_l2, str(l1["id"]), taxonomy)
            selection = (str(l1["id"]), str(l2["code"]))

        report_date, holdings = fetch_latest_report(report_date=args.report_date or None)
        history = fetch_sw_classification_history()
        classification = build_classification_asof(history, report_date, taxonomy)
        if selection is None:
            summary = aggregate_all_report(
                holdings, classification, taxonomy, report_date=report_date
            )
        else:
            summary = aggregate_report(
                holdings,
                classification,
                taxonomy,
                l1_id=selection[0],
                l2_code=selection[1],
                report_date=report_date,
            )
        json_path, markdown_path = write_report_files(summary, args.output_dir)
    except Exception as exc:  # surfaced in the Action log; never create a partial/stale result
        print(f"fund-industry failed; no report was published: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(render_markdown(summary))
    print(f"\nJSON: {Path(json_path).as_posix()}\nMarkdown: {Path(markdown_path).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

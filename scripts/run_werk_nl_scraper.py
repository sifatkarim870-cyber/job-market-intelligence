#!/usr/bin/env python
"""Run the UWV Werk.nl (Netherlands) scraper.

Usage:
    python scripts/run_werk_nl_scraper.py [--no-db] [--max-jobs N]
                                          [--start-page N]
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.werk_nl import WerkNlPipeline, WerkNlSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape UWV Werk.nl (Netherlands).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap detail pages fetched this run.")
    ap.add_argument(
        "--start-page",
        type=int,
        default=None,
        help="Pin the rotating page window start (reproducible runs).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.start_page is not None:
        overrides["start_page"] = args.start_page
    settings = WerkNlSettings(**overrides)

    store_db = not args.no_db
    result = WerkNlPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("UWV WERK.NL (NETHERLANDS) - RUN SUMMARY")
    print("=" * 64)
    print(f"Total vacancies reported:  {result.total_results}")
    print(f"Search pages fetched:      {result.pages_scanned}")
    print(f"Vacancies fetched:         {result.raw_count}")
    print(f"Detail fetch failures:     {result.fetch_failures}")
    print(f"Parsed:                    {result.parsed_count}")
    print(f"Cleaned:                   {result.cleaned_count}")
    print(f"Batch validation:          {'PASSED' if result.validation_passed else 'FAILED'}")
    if args.no_db:
        print("DRY-RUN MODE (--no-db): Database storage skipped.")
    else:
        print(f"Inserted:                  {result.inserted_count}")
        print(f"Updated:                   {result.updated_count}")
        print(f"Unchanged:                 {result.unchanged_count}")
        print(f"Failed to persist:         {result.failed_count}")
    if result.issues:
        print(f"Issues ({len(result.issues)}):")
        for issue in result.issues[:5]:
            print(f"  - {issue}")
    print("=" * 64)

    return runner_exit_code(result, store_db=store_db)


if __name__ == "__main__":
    sys.exit(main())

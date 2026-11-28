#!/usr/bin/env python
"""Run the work.ua (Ukraine) scraper.

Usage:
    python scripts/run_work_ua_scraper.py [--no-db] [--max-jobs N]
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.work_ua import WorkUaPipeline, WorkUaSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape work.ua (Ukraine).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap ad pages fetched this run.")
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    settings = WorkUaSettings(**overrides)

    store_db = not args.no_db
    result = WorkUaPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("WORK.UA (UKRAINE) - RUN SUMMARY")
    print("=" * 64)
    print(f"Total vacancies reported:  {result.total_results}")
    print(f"Listing pages fetched:     {result.pages_scanned}")
    print(f"Ad pages fetched:          {result.pages_fetched}")
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

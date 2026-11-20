#!/usr/bin/env python
"""Run the Jobindex (Denmark, jobindex.dk) scraper.

Usage:
    python scripts/run_jobindex_dk_scraper.py [--no-db] [--max-jobs N]
                                              [--area-pages N] [--start-offset N]
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.jobindex_dk import JobIndexPipeline, JobIndexSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Jobindex (Denmark).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap postings fetched this run.")
    ap.add_argument("--area-pages", type=int, default=None, help="Area listing pages to walk.")
    ap.add_argument(
        "--start-offset",
        type=int,
        default=None,
        help="Pin the rotating area window start (reproducible runs).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.area_pages is not None:
        overrides["max_area_pages"] = args.area_pages
    if args.start_offset is not None:
        overrides["start_offset"] = args.start_offset
    settings = JobIndexSettings(**overrides)

    store_db = not args.no_db
    result = JobIndexPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("JOBINDEX.DK (DENMARK) - RUN SUMMARY")
    print("=" * 64)
    print(f"Listing pages scraped:   {result.pages_scraped}")
    print(f"Ads discovered:          {result.discovered_count}")
    print(f"Ad pages fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    if args.no_db:
        print("DRY-RUN MODE (--no-db): Database storage skipped.")
    else:
        print(f"Inserted:                {result.inserted_count}")
        print(f"Updated:                 {result.updated_count}")
        print(f"Unchanged:               {result.unchanged_count}")
        print(f"Failed to persist:       {result.failed_count}")
    if result.issues:
        print(f"Issues ({len(result.issues)}):")
        for issue in result.issues[:5]:
            print(f"  - {issue}")
    print("=" * 64)

    return runner_exit_code(result, store_db=store_db)


if __name__ == "__main__":
    sys.exit(main())

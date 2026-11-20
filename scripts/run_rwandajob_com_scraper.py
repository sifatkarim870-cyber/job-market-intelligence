#!/usr/bin/env python
"""Run the Rwandajob.com (Rwanda) scraper.

Usage:
    python scripts/run_rwandajob_com_scraper.py [--no-db] [--max-jobs N]
                                                [--pages N] [--start-offset N]
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.rwandajob_com import (
    RwandaJobPipeline,
    RwandaJobSettings,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Rwandajob.com (Rwanda).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap postings fetched this run.")
    ap.add_argument("--pages", type=int, default=None, help="Search pages to walk.")
    ap.add_argument(
        "--start-offset",
        type=int,
        default=None,
        help="Pin the rotating window start (reproducible runs).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    if args.start_offset is not None:
        overrides["start_offset"] = args.start_offset
    settings = RwandaJobSettings(**overrides)

    store_db = not args.no_db
    result = RwandaJobPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("RWANDAJOB.COM (RWANDA) - RUN SUMMARY")
    print("=" * 64)
    print(f"Search pages scraped:    {result.pages_scraped}")
    print(f"Postings fetched:        {result.raw_count}")
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

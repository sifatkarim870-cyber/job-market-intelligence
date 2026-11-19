#!/usr/bin/env python
"""Run the TopJobs (topjobs.lk, Sri Lanka) scraper."""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.topjobs_lk import (
    TopJobsLkPipeline,
    TopJobsLkSettings,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape TopJobs (Sri Lanka).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap postings fetched this run.")
    ap.add_argument("--pages", type=int, default=None, help="Listing pages to walk.")
    ap.add_argument(
        "--no-details",
        action="store_true",
        help="Skip ad pages (no body text, no employment labels).",
    )
    ap.add_argument(
        "--start-offset",
        type=int,
        default=None,
        help="Pin the rotating window start (reproducible runs).",
    )
    args = ap.parse_args()

    overrides = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_listing_pages"] = args.pages
    if args.no_details:
        overrides["fetch_details"] = False
    if args.start_offset is not None:
        overrides["start_offset"] = args.start_offset
    settings = TopJobsLkSettings(**overrides)

    store_db = not args.no_db
    result = TopJobsLkPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("TOPJOBS (SRI LANKA) - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"  with body text:        {result.with_description}")
    print(f"  image-only body:       {result.image_only}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (no salary published)")
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

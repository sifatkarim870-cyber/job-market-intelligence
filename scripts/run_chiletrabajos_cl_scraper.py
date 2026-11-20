#!/usr/bin/env python
"""Run the Chiletrabajos (Chile) scraper.

Usage:
    python scripts/run_chiletrabajos_cl_scraper.py [--no-db] [--max-jobs N]
                                                   [--start-offset N]
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.chiletrabajos_cl import (
    ChiletrabajosClPipeline,
    ChiletrabajosClSettings,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Chiletrabajos (Chile).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap ad pages fetched this run.")
    ap.add_argument(
        "--start-offset",
        type=int,
        default=None,
        help="Pin the rotating tail window start (reproducible runs).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.start_offset is not None:
        overrides["start_offset"] = args.start_offset
    settings = ChiletrabajosClSettings(**overrides)

    store_db = not args.no_db
    result = ChiletrabajosClPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("CHILETRABAJOS (CHILE) - RUN SUMMARY")
    print("=" * 64)
    print(f"Sitemap entries available: {result.sitemap_entries}")
    print(f"Ad pages fetched:          {result.pages_fetched}")
    print(f"Fetch failures:            {result.fetch_failures}")
    print(f"Postings fetched:          {result.raw_count}")
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

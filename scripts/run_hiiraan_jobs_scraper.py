#!/usr/bin/env python
"""Run the Hiiraan jobs scraper (Somalia)."""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.hiiraan_jobs import HiiraanJobsPipeline, HiiraanJobsSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Hiiraan jobs (Somalia).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap postings fetched this run.")
    ap.add_argument("--pages", type=int, default=None, help="Listing pages to walk.")
    args = ap.parse_args()

    overrides = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = HiiraanJobsSettings(**overrides)

    result = HiiraanJobsPipeline(settings=settings).run(store_db=not args.no_db)
    print("\n" + "=" * 64)
    print("HIIRAAN JOBS - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (no salary published)")
    print("Posting dates:           0 (no posting date published)")
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

    persisted = result.inserted_count + result.updated_count + result.unchanged_count
    if not args.no_db and not result.validation_passed and persisted == 0:
        print("\nERROR: the run persisted 0 rows and batch validation FAILED.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

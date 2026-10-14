#!/usr/bin/env python
"""Run the Wellfound scraper.

    uv run python scripts/run_wellfound_scraper.py                 # fetch + persist
    uv run python scripts/run_wellfound_scraper.py --no-db         # dry run
    uv run python scripts/run_wellfound_scraper.py --max-jobs 100   # smaller walk

No key or registration is needed. Discovery walks only ``/location/<country>``
and ``/role/l/<role>/<country>`` pages, because ``/jobs`` ignores its own
``page`` parameter and would re-read page 1 forever.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.wellfound import WellfoundPipeline, WellfoundSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Wellfound (wellfound.com).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: WELLFOUND_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages-per-listing",
        type=int,
        default=None,
        help="Listing pages to walk per listing path (default: WELLFOUND_MAX_PAGES_PER_LISTING).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages_per_listing is not None:
        overrides["max_pages_per_listing"] = args.pages_per_listing
    settings = WellfoundSettings(**overrides)

    result = WellfoundPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("WELLFOUND - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Run the Careers24 scraper.

    uv run python scripts/run_careers24_scraper.py                 # fetch + persist
    uv run python scripts/run_careers24_scraper.py --no-db         # dry run
    uv run python scripts/run_careers24_scraper.py --max-jobs 30   # smaller walk

No key, registration or proxy is needed. South Africa had zero coverage in the
corpus before this source.

robots.txt has no ``User-agent: *`` group, which under RFC 9309 means the
crawler is subject to no rule in the file -- see the package docstring for why
that is worth reading rather than assuming a default either way.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.careers24 import Careers24Pipeline, Careers24Settings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Careers24 (careers24.com).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: CAREERS24_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default: CAREERS24_MAX_PAGES, 10 adverts per page).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = Careers24Settings(**overrides)

    result = Careers24Pipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("CAREERS24 - RUN SUMMARY")
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

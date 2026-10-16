#!/usr/bin/env python
"""Run the CareerJunction scraper.

    uv run python scripts/run_careerjunction_scraper.py                 # fetch + persist
    uv run python scripts/run_careerjunction_scraper.py --no-db         # dry run
    uv run python scripts/run_careerjunction_scraper.py --max-jobs 10   # smaller walk

No key, registration or proxy is needed. South Africa had 40 rows from careers24
before this source; CareerJunction adds 25 from a different employer base.

Discovery walks /jobs (25 postings, single page -- the pager is ignored).
Detail pages carry a schema.org JobPosting in a JSON-LD block, but the JSON is
malformed -- the description string contains raw newlines -- so the parser
uses json.loads(block, strict=False).
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.careerjunction import CareerJunctionPipeline, CareerJunctionSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape CareerJunction (careerjunction.co.za).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: CAREERJUNCTION_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default: CAREERJUNCTION_MAX_PAGES, 1 page, 25 postings).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = CareerJunctionSettings(**overrides)

    result = CareerJunctionPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("CAREERJUNCTION - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (CareerJunction publishes 'R Undisclosed' -- measured 0/1)")
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

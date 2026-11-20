#!/usr/bin/env python
"""Run the Revolico (Cuba) scraper."""

from __future__ import annotations

import argparse
import sys

from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.revolico_cu import (
    RevolicoCuPipeline,
    RevolicoCuSettings,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Revolico (Cuba jobs).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Cap ads fetched this run.")
    ap.add_argument("--pages", type=int, default=None, help="Listing pages to walk.")
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = RevolicoCuSettings(**overrides)

    store_db = not args.no_db
    result = RevolicoCuPipeline(settings=settings).run(store_db=store_db)

    print("\n" + "=" * 64)
    print("REVOLICO (CUBA) - RUN SUMMARY")
    print("=" * 64)
    print(f"Ads fetched:             {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries: none disclosed (the board's price field is unreliable)")
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

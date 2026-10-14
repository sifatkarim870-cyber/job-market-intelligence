#!/usr/bin/env python
"""Run the Job Bank Canada scraper.

uv run python scripts/run_jobbank_scraper.py                 # fetch + persist
uv run python scripts/run_jobbank_scraper.py --no-db         # dry run
uv run python scripts/run_jobbank_scraper.py --max-jobs 100  # smaller walk
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.jobbank import JobBankPipeline, JobBankSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Job Bank Canada (jobbank.gc.ca).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: JOBBANK_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages-per-term", type=int, default=None, help="Pages to walk per occupational term."
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages_per_term is not None:
        overrides["max_pages_per_term"] = args.pages_per_term
    settings = JobBankSettings(**overrides)

    result = JobBankPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("JOB BANK CANADA - RUN SUMMARY")
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

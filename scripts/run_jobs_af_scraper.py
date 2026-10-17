#!/usr/bin/env python
"""Run the Jobs.af scraper.

    uv run python scripts/run_jobs_af_scraper.py                 # fetch + persist
    uv run python scripts/run_jobs_af_scraper.py --no-db         # dry run
    uv run python scripts/run_jobs_af_scraper.py --max-jobs 10   # smaller walk

No key, registration or proxy is needed. Adds a second Afghan board alongside
ACBAR, with a different employer base.

Two measured traps:
  * addressCountry is the NAME 'Afghanistan', not the ISO code 'AF' -- normalized
    in the cleaner, otherwise the row resolves to no country and collapses onto
    the global-remote location;
  * datePosted carries milliseconds and a truncated '+00' offset
    ('2026-10-17 10:48:27.175+00'), which is not ISO 8601 -- the parser takes the
    leading YYYY-MM-DD by regex, so a strict parser would lose every date.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.jobs_af import JobsAfPipeline, JobsAfSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Jobs.af (jobs.af, Afghanistan).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: JOBS_AF_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default 1 -- this board has no pager).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = JobsAfSettings(**overrides)

    result = JobsAfPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("JOBS.AF - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (no baseSalary on the measured posting)")
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

    # A run that persisted nothing while reporting a failed batch validation is
    # breakage, not a quiet board.
    persisted = result.inserted_count + result.updated_count + result.unchanged_count
    if not args.no_db and not result.validation_passed and persisted == 0:
        print(
            "\nERROR: the run persisted 0 rows and batch validation FAILED. "
            "This is breakage, not a quiet board -- exiting non-zero so CI cannot "
            "report success on a source that collected nothing."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Run the Jobweb Ghana scraper.

    uv run python scripts/run_jobwebghana_scraper.py                 # fetch + persist
    uv run python scripts/run_jobwebghana_scraper.py --no-db         # dry run
    uv run python scripts/run_jobwebghana_scraper.py --max-jobs 30   # smaller walk

No key, registration or proxy is needed. Ghana had ZERO coverage in the corpus
before this source.

Pagination is path-based (/jobs/page/N/) because robots.txt disallows every
query string (/*?*).

NOTE ON SALARY: the board publishes the same 1500-8000 GHS/month block on every
posting measured -- a site-wide placeholder, not a posted figure. It is recorded
for audit and deliberately NOT stored.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.jobwebghana import JobwebGhanaPipeline, JobwebGhanaSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Jobweb Ghana (jobwebghana.com).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: JOBWEBGHANA_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default: JOBWEBGHANA_MAX_PAGES).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = JobwebGhanaSettings(**overrides)

    result = JobwebGhanaPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("JOBWEB GHANA - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 stored -- the board publishes one identical")
    print("                         1500-8000 GHS/month placeholder on every posting")
    print("                         (5 of 5 measured, CEO to CCTV guard). Rejected.")
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
    # breakage, not a quiet board. Exiting 0 there is a green tick on a source
    # that collected nothing.
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

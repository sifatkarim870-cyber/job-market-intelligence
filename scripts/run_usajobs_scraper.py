#!/usr/bin/env python
"""Run the USAJOBS scraper (data.usajobs.gov + usajobs.gov job pages).

    uv run python scripts/run_usajobs_scraper.py                 # fetch + persist
    uv run python scripts/run_usajobs_scraper.py --no-db         # dry run
    uv run python scripts/run_usajobs_scraper.py --max-jobs 50   # smaller walk

Needs a free data.gov key from https://developer.usajobs.gov/. Supply it as
``USAJOBS_API_KEY``, or as a file path in ``USAJOBS_API_KEY_FILE`` -- the
pipeline aborts immediately when neither is set, rather than reporting a
successful run that persisted nothing.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.usajobs import USAJobsPipeline, USAJobsSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape USAJOBS (data.usajobs.gov).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: USAJOBS_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--results-per-page",
        type=int,
        default=None,
        help="Postings per search request (1-500, default: 50).",
    )
    ap.add_argument(
        "--no-job-pages",
        action="store_true",
        help=(
            "Skip the per-posting page fetch. Far cheaper, but the corpus then "
            "gets QualificationSummary instead of the full duties and requirements."
        ),
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.results_per_page is not None:
        overrides["results_per_page"] = args.results_per_page
    if args.no_job_pages:
        overrides["fetch_job_pages"] = False
    settings = USAJobsSettings(**overrides)

    result = USAJobsPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("USAJOBS - RUN SUMMARY")
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

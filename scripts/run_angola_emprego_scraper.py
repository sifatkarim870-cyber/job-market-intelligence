#!/usr/bin/env python
"""Run the Angola Emprego scraper.

    uv run python scripts/run_angola_emprego_scraper.py                 # fetch + persist
    uv run python scripts/run_angola_emprego_scraper.py --no-db         # dry run
    uv run python scripts/run_angola_emprego_scraper.py --max-jobs 30   # smaller walk

No key, registration or proxy is needed. Angola had ZERO coverage in the corpus
before this source.

Discovery walks /vagas?page=N (15 postings per page, real pager). robots.txt
disallows the query-parameter searches /vagas?q=, /vagas?location= and
/vagas?category= but not ?page=, so the pager is compliant.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.angola_emprego import AngolaEmpregoPipeline, AngolaEmpregoSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Angola Emprego (angolaemprego.com).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: ANGOLA_EMPREGO_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default: ANGOLA_EMPREGO_MAX_PAGES, 15 postings per page).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = AngolaEmpregoSettings(**overrides)

    result = AngolaEmpregoPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("ANGOLA EMPREGO - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (Angola Emprego publishes no baseSalary -- measured 0/2)")
    print("employmentType:          arrives as a LIST -- handled, mapped to employment_types.code")
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
    # broken, not quiet. Exiting 0 there is a green tick on a source that
    # collected nothing -- the silent failure this guards against. A run that
    # inserted *some* rows stays green, because a degraded feed is still a
    # working feed.
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

#!/usr/bin/env python
"""Run the Apna scraper.

    uv run python scripts/run_apna_scraper.py                 # fetch + persist
    uv run python scripts/run_apna_scraper.py --no-db         # dry run
    uv run python scripts/run_apna_scraper.py --max-jobs 50   # smaller walk

No key, registration or proxy is needed. India had zero coverage in the corpus
before this source, and it is the highest-coverage salary source in it: 30 of 30
postings measured carried a monthly INR band.

robots.txt disallows only ``/*.infra.apna.co/``, so ``/jobs`` and
``/job/<city>/<slug>-<id>`` are fetched and nothing else is.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.apna import ApnaPipeline, ApnaSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Apna (apna.co).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: APNA_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default: APNA_MAX_PAGES, 25 postings per page).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = ApnaSettings(**overrides)

    result = ApnaPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("APNA - RUN SUMMARY")
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

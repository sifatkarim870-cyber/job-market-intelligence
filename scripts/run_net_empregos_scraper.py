#!/usr/bin/env python
"""Run the Net-Empregos scraper.

    uv run python scripts/run_net_empregos_scraper.py                 # fetch + persist
    uv run python scripts/run_net_empregos_scraper.py --no-db         # dry run
    uv run python scripts/run_net_empregos_scraper.py --max-jobs 30   # smaller walk

No key, registration or proxy is needed. Portugal had zero coverage in the
corpus before this source.

Discovery walks /jobs?page=N (18 postings per page, real pagination). Detail
pages carry a schema.org JobPosting in a JSON-LD block, but the JSON is
malformed -- the description string contains raw newlines -- so the parser
uses json.loads(block, strict=False).
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.net_empregos import NetEmpregosPipeline, NetEmpregosSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Net-Empregos (net-empregos.com).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: NET_EMPREGOS_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Listing pages to walk (default: NET_EMPREGOS_MAX_PAGES, 18 postings per page).",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages is not None:
        overrides["max_pages"] = args.pages
    settings = NetEmpregosSettings(**overrides)

    result = NetEmpregosPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("NET-EMPREGOS - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (Net-Empregos publishes no baseSalary -- measured 0/3)")
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

#!/usr/bin/env python
"""Run the Alfred scraper.

    uv run python scripts/run_alfred_scraper.py                 # fetch + persist
    uv run python scripts/run_alfred_scraper.py --no-db         # dry run
    uv run python scripts/run_alfred_scraper.py --max-jobs 30   # smaller walk

No key, registration or proxy is needed. Iceland had zero coverage in the
corpus before this source.

Discovery reads ``sitemap-jobs.xml`` (624 posting URLs), not the homepage: the
homepage feed serves 27 records and every pagination attempt returns a
byte-identical page. robots.txt disallows ``/api/*`` and the filter parameters,
so the sitemap is both the compliant route and the only one that reaches the
whole board.

Expect a slow run: detail pages are 240-250 KB and the default is 1s between
requests, so ~150 postings takes about five minutes.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.alfred import AlfredPipeline, AlfredSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Alfred (alfred.is).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: ALFRED_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds between requests (default: ALFRED_INTER_REQUEST_DELAY_SECONDS, 1.0).",
    )
    ap.add_argument(
        "--keep-general-application",
        action="store_true",
        help="Keep the sitemap's general-application pages instead of dropping them.",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.delay is not None:
        overrides["inter_request_delay_seconds"] = args.delay
    if args.keep_general_application:
        overrides["drop_general_application_pages"] = False
    settings = AlfredSettings(**overrides)

    result = AlfredPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("ALFRED - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"General-application:     {result.general_application_dropped} dropped (not vacancies)")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                0 (Alfred publishes no baseSalary -- measured 0/10)")
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

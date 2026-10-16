#!/usr/bin/env python
"""Run the Mustakbil scraper.

    uv run python scripts/run_mustakbil_scraper.py                 # fetch + persist
    uv run python scripts/run_mustakbil_scraper.py --no-db         # dry run
    uv run python scripts/run_mustakbil_scraper.py --max-jobs 30   # smaller walk

No key, registration or proxy is needed. Pakistan had zero coverage in the
corpus before this source.

There is no working pagination on this board -- ``/jobs?page=2`` is byte-identical
to page 1 -- so discovery walks nine category paths instead, for 123 distinct
postings. Expect the run to take roughly ten minutes: the site throttles at the
connection level and the default 4-second inter-request delay is measured, not
generous.
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.mustakbil import MustakbilPipeline, MustakbilSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Mustakbil (mustakbil.com).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap postings fetched this run (default: MUSTAKBIL_MAX_JOBS_PER_RUN).",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds between requests (default: MUSTAKBIL_INTER_REQUEST_DELAY_SECONDS, 4.0). "
        "Lowering this makes detail fetches fail with ConnectionError.",
    )
    args = ap.parse_args()

    overrides: dict = {}
    if args.max_jobs is not None:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.delay is not None:
        overrides["inter_request_delay_seconds"] = args.delay
    settings = MustakbilSettings(**overrides)

    result = MustakbilPipeline(settings=settings).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print("MUSTAKBIL - RUN SUMMARY")
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
    if result.fetch_failures:
        print(
            f"\nNOTE: {result.fetch_failures} fetch failure(s). Mustakbil throttles "
            "at the connection\n      level; raise --delay if this is much above zero."
        )
    if result.issues:
        print(f"Issues ({len(result.issues)}):")
        for issue in result.issues[:5]:
            print(f"  - {issue}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())

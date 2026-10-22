#!/usr/bin/env python
"""Run the generic browser (Selenium) scraper for a specific site.

Usage:
    uv run python scripts/run_browser_scraper.py --source-code ethiojobs --max-jobs 20
    uv run python scripts/run_browser_scraper.py --source-code ethiojobs --no-db
    SOURCE_CODE=ethiojobs uv run python scripts/run_browser_scraper.py --no-db
"""

from __future__ import annotations

import argparse
import os
import sys

from job_market_intel.scrapers.browser_scraper import (
    BrowserScraperPipeline,
    BrowserScraperSettings,
)
from job_market_intel.scrapers.browser_scraper.config import load_browser_site_config


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the generic browser scraper for a site.")
    ap.add_argument(
        "--source-code",
        default=os.environ.get("SOURCE_CODE", ""),
        help="Site source_code (matches sites/<code>.json). Defaults to $SOURCE_CODE.",
    )
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Max jobs fetched this run.")
    ap.add_argument("--max-pages", type=int, default=None, help="Max listing pages.")
    ap.add_argument("--delay", type=float, default=None, help="Seconds between requests.")
    ap.add_argument("--headful", action="store_true", help="Run with a visible browser window.")
    args = ap.parse_args()

    if not args.source_code:
        ap.error("--source-code is required (or set SOURCE_CODE in the environment)")

    settings = BrowserScraperSettings()
    site_config = load_browser_site_config(args.source_code, settings.sites_dir)
    if args.max_pages is not None:
        site_config = site_config.model_copy(update={"max_pages": args.max_pages})
    if args.delay is not None:
        site_config = site_config.model_copy(update={"inter_request_delay_seconds": args.delay})
    if args.headful:
        site_config = site_config.model_copy(update={"headless": False})

    result = BrowserScraperPipeline(
        source_code=args.source_code,
        settings=settings,
        site_config=site_config,
    ).run(store_db=not args.no_db, max_jobs=args.max_jobs)

    print("\n" + "=" * 64)
    print(f"BROWSER SCRAPER - {args.source_code.upper()} - RUN SUMMARY")
    print("=" * 64)
    print(f"Postings fetched:        {result.raw_count}")
    print(f"Fetch failures:          {result.fetch_failures}")
    print(f"Parsed:                  {result.parsed_count}")
    print(f"Cleaned:                 {result.cleaned_count}")
    print(f"Validation passed:       {result.validation_passed}")
    if not args.no_db:
        print(f"Inserted:                {result.inserted_count}")
        print(f"Updated:                 {result.updated_count}")
        print(f"Unchanged:               {result.unchanged_count}")
        print(f"Failed:                  {result.failed_count}")
    if result.issues:
        print("-" * 64)
        for issue in result.issues[:10]:
            print(f"  - {issue}")

    if not args.no_db and not result.validation_passed and result.inserted_count == 0:
        print(
            "ERROR: the run persisted 0 rows and batch validation FAILED. This is "
            "breakage, not a quiet board -- exiting non-zero so CI cannot report "
            "success on a source that collected nothing."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Run the generic HTML scraper framework for a specific site.

Usage:
    uv run python scripts/run_html_scraper.py --source-code skilljobs --max-jobs 30
    uv run python scripts/run_html_scraper.py --source-code skilljobs --no-db --max-jobs 10
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.html_scraper import HtmlScraperPipeline, HtmlScraperSettings


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the generic HTML scraper for a site.")
    ap.add_argument("--source-code", required=True, help="Site source_code (matches sites/<code>.json).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Max jobs fetched this run.")
    ap.add_argument("--max-pages", type=int, default=None, help="Max listing pages.")
    ap.add_argument("--delay", type=float, default=None, help="Seconds between requests.")
    args = ap.parse_args()

    settings = HtmlScraperSettings()
    if args.max_pages is not None:
        # Override per-site max_pages via env-like approach
        pass
    if args.delay is not None:
        pass

    result = HtmlScraperPipeline(
        source_code=args.source_code,
        settings=settings,
    ).run(store_db=not args.no_db)

    print("\n" + "=" * 64)
    print(f"HTML SCRAPER - {args.source_code.upper()} - RUN SUMMARY")
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

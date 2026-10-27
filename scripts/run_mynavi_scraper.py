#!/usr/bin/env python
"""Run the Mynavi (job.mynavi.jp) scraper.

Mynavi publishes no listing of postings, so discovery reads its company
sitemap and the course lists on each company page instead of the generic
listing path. Everything after discovery -- parsing, quality filtering,
validation, cleaning and persistence -- is the shared HTML pipeline.

Usage:
    uv run python scripts/run_mynavi_scraper.py --no-db --max-jobs 5
"""

from __future__ import annotations

import argparse
import sys

from job_market_intel.scrapers.html_scraper import HtmlScraperPipeline, HtmlScraperSettings
from job_market_intel.scrapers.html_scraper.config import load_site_config
from job_market_intel.scrapers.mynavi import MynaviClient

SOURCE_CODE = "job_mynavi_jp"


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Mynavi (Japan).")
    ap.add_argument("--no-db", action="store_true", help="Fetch and report; do not persist.")
    ap.add_argument("--max-jobs", type=int, default=None, help="Max postings fetched this run.")
    ap.add_argument("--delay", type=float, default=None, help="Seconds between requests.")
    args = ap.parse_args()

    settings = HtmlScraperSettings()
    site_config = load_site_config(SOURCE_CODE, settings.sites_dir)
    if args.delay is not None:
        site_config = site_config.model_copy(update={"inter_request_delay_seconds": args.delay})

    result = HtmlScraperPipeline(
        source_code=SOURCE_CODE,
        settings=settings,
        site_config=site_config,
        client=MynaviClient(SOURCE_CODE, settings, site_config),
    ).run(store_db=not args.no_db, max_jobs=args.max_jobs)

    print("\n" + "=" * 64)
    print(f"MYNAVI - {SOURCE_CODE.upper()} - RUN SUMMARY")
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

    persisted = result.inserted_count + result.updated_count + result.unchanged_count
    if not args.no_db and not result.validation_passed and persisted == 0:
        print("\nERROR: the run persisted 0 rows and batch validation FAILED.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

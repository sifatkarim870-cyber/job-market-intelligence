#!/usr/bin/env python
"""Run the OCC Mundial (Mexico) scraper end-to-end.

Fetches, parses, validates, cleans and (unless ``--no-db``) persists OCC
postings into PostgreSQL, logging a scraping session and performing change
detection through the shared HTML pipeline.

Usage:
    SOURCE_CODE=occ_com_mx python scripts/run_occ_com_mx_scraper.py --no-db
    python scripts/run_occ_com_mx_scraper.py --max-jobs 30
"""

from __future__ import annotations

import argparse
import os

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.browser_scraper import BrowserScraperSettings
from job_market_intel.scrapers.browser_scraper.config import load_browser_site_config
from job_market_intel.scrapers.occ_com_mx import SOURCE_CODE, OccComMxPipeline


def _max_jobs_from_env() -> int | None:
    """``OCC_COM_MX_MAX_JOBS_PER_RUN`` as an int, or ``None`` when unset."""
    raw = os.environ.get("OCC_COM_MX_MAX_JOBS_PER_RUN", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("OCC_COM_MX_MAX_JOBS_PER_RUN is not an integer: {!r}", raw)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="OCC Mundial (Mexico) job scraper")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Fetch, parse, validate and clean without persisting to PostgreSQL.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Cap postings fetched this run (default: OCC_COM_MX_MAX_JOBS_PER_RUN).",
    )
    parser.add_argument("--max-pages", type=int, help="Override the listing page cap.")
    parser.add_argument("--headful", action="store_true", help="Run a visible browser.")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    browser_settings = BrowserScraperSettings()
    site_config = load_browser_site_config(SOURCE_CODE, browser_settings.sites_dir)
    if args.max_pages is not None:
        site_config = site_config.model_copy(update={"max_pages": args.max_pages})
    if args.headful:
        site_config = site_config.model_copy(update={"headless": False})

    max_jobs = args.max_jobs if args.max_jobs is not None else _max_jobs_from_env()
    store_db = not args.no_db

    logger.info("Starting OCC Mundial pipeline (store_db={}, max_jobs={}).", store_db, max_jobs)
    result = OccComMxPipeline(
        source_code=SOURCE_CODE,
        settings=browser_settings,
        site_config=site_config,
    ).run(store_db=store_db, max_jobs=max_jobs)

    print()
    print("=" * 72)
    print("OCC MUNDIAL (MEXICO) - RUN SUMMARY")
    print("=" * 72)
    print(f"Postings fetched:          {result.raw_count}")
    print(f"Fetch failures:           {result.fetch_failures}")
    print(f"Parsed:                   {result.parsed_count}")
    print(f"Cleaned & normalized:     {result.cleaned_count}")
    print(f"Batch validation:         {'PASSED' if result.validation_passed else 'FAILED'}")
    print("Salaries:                 MXN/month when published, else undisclosed")
    if result.issues:
        for issue in result.issues[:5]:
            print(f"  - {issue}")
    print()
    if store_db:
        print("DATABASE PERSISTENCE & DEDUPLICATION:")
        print(f"  New jobs inserted:      {result.inserted_count}")
        print(f"  Jobs updated:           {result.updated_count}")
        print(f"  Jobs unchanged:         {result.unchanged_count}")
        print(f"  Persistence failures:   {result.failed_count}")
    else:
        print("DRY-RUN MODE (--no-db active): Database storage skipped.")
    print("=" * 72)

    return runner_exit_code(result, store_db=store_db)


if __name__ == "__main__":
    raise SystemExit(main())

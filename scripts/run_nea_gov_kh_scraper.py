"""Manual entry point to run the NEA Cambodia pipeline end-to-end.

Fetches, parses, validates, cleans and persists National Employment Agency
(Cambodia) vacancies into PostgreSQL, logging a scraping session and
performing change detection via content hashing.

Usage:
    python scripts/run_nea_gov_kh_scraper.py [--no-db] [--max-jobs N] [--pages N]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.nea_gov_kh import (
    NeaGovKhError,
    NeaGovKhPipeline,
    NeaGovKhSettings,
)


def main() -> int:
    """Run the NEA Cambodia pipeline and print a summary."""
    parser = argparse.ArgumentParser(description="NEA Cambodia Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Fetch, parse, validate and clean without persisting to PostgreSQL.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Override NEA_GOV_KH_MAX_JOBS_PER_RUN for this run.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        help="Override NEA_GOV_KH_PAGES_PER_RUN for this run.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    overrides: dict = {}
    if args.max_jobs:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages:
        overrides["pages_per_run"] = args.pages
    pipeline = NeaGovKhPipeline(settings=NeaGovKhSettings(**overrides))
    store_db = not args.no_db

    logger.info("Starting NEA Cambodia pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except NeaGovKhError as exc:
        logger.error("NEA Cambodia pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 72)
    print("NEA CAMBODIA - RUN SUMMARY")
    print("=" * 72)
    print(f"Raw vacancy pages fetched: {run_result.raw_count}")
    print(f"Fetch failures:            {run_result.fetch_failures}")
    print(f"Successfully parsed:       {run_result.parsed_count}")
    print(f"Cleaned & normalized:      {run_result.cleaned_count}")
    print(f"Batch validation:          {'PASSED' if run_result.validation_passed else 'FAILED'}")
    print("Salaries:                  USD/month when published, else undisclosed (USD, monthly)")
    if run_result.issues:
        for issue in run_result.issues[:5]:
            print(f"  - {issue}")
    print()
    if store_db:
        print("DATABASE PERSISTENCE & DEDUPLICATION:")
        print(f"  Scraping Session ID:   {run_result.session_id}")
        print(f"  New jobs inserted:     {run_result.inserted_count}")
        print(f"  Jobs updated:          {run_result.updated_count}")
        print(f"  Jobs unchanged:        {run_result.unchanged_count}")
        print(f"  Persistence failures:  {run_result.failed_count}")
    else:
        print("DRY-RUN MODE (--no-db active): Database storage skipped.")
    print("=" * 72)

    logger.info("NEA Cambodia pipeline run finished.")
    return runner_exit_code(run_result, store_db=store_db)


if __name__ == "__main__":
    raise SystemExit(main())

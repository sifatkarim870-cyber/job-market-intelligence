"""Manual entry point to run the Kariyer.net pipeline end-to-end.

Fetches, parses, validates, cleans and persists Kariyer.net postings (Turkiye)
into PostgreSQL, logging a scraping session and performing change detection via
content hashing.

Usage:
    python scripts/run_kariyer_net_scraper.py [--no-db] [--max-jobs N]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.kariyer_net import (
    KariyerNetError,
    KariyerNetPipeline,
    KariyerNetSettings,
)


def main() -> int:
    """Run the Kariyer.net pipeline and print a summary."""
    parser = argparse.ArgumentParser(description="Kariyer.net Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Fetch, parse, validate and clean without persisting to PostgreSQL.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Override KARIYER_NET_MAX_JOBS_PER_RUN for this run.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        help="Override KARIYER_NET_MAX_PAGES_PER_RUN for this run.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    overrides: dict = {}
    if args.max_jobs:
        overrides["max_jobs_per_run"] = args.max_jobs
    if args.pages:
        overrides["max_pages_per_run"] = args.pages
    pipeline = KariyerNetPipeline(settings=KariyerNetSettings(**overrides))
    store_db = not args.no_db

    logger.info("Starting Kariyer.net pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except KariyerNetError as exc:
        logger.error("Kariyer.net pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("KARIYER.NET PIPELINE - RUN SUMMARY")
    print("=" * 70)
    print(f"Raw records fetched:     {run_result.raw_count}")
    print(f"Detail fetch failures:   {run_result.fetch_failures}")
    print(f"Successfully parsed:     {run_result.parsed_count}")
    print(f"Cleaned & normalized:    {run_result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if run_result.validation_passed else 'FAILED'}")
    print("Salaries:                undisclosed (jobSalaryBudget is null on TR ads)")
    if run_result.issues:
        for issue in run_result.issues:
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
    print("=" * 70)

    logger.info("Kariyer.net pipeline run finished.")
    return runner_exit_code(run_result, store_db=store_db)


if __name__ == "__main__":
    raise SystemExit(main())

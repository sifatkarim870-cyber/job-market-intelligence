"""Manual entry point to run the Jobicy pipeline end-to-end.

Usage:
    python scripts/run_jobicy_scraper.py [--no-db] [--max-jobs N]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.jobicy import (
    JobicyError,
    JobicyPipeline,
    JobicySettings,
)


def main() -> int:
    """Run the Jobicy pipeline and print a summary.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the scrape failed.
    """
    parser = argparse.ArgumentParser(description="Jobicy Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Fetch, parse, validate and clean without persisting to PostgreSQL.",
    )
    parser.add_argument("--max-jobs", type=int, help="Override JOBICY_MAX_JOBS_PER_RUN.")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    overrides: dict = {}
    if args.max_jobs:
        overrides["max_jobs_per_run"] = args.max_jobs
    pipeline = JobicyPipeline(settings=JobicySettings(**overrides))
    store_db = not args.no_db

    logger.info("Starting Jobicy pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except JobicyError as exc:
        logger.error("Jobicy pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("JOBICY PIPELINE — RUN SUMMARY")
    print("=" * 70)
    print(f"Raw records fetched:     {run_result.raw_count}")
    print(f"Successfully parsed:     {run_result.parsed_count}")
    print(f"Dropped by focus filter: {run_result.filtered_count}")
    print(f"Cleaned & normalized:    {run_result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if run_result.validation_passed else 'FAILED'}")
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

    logger.info("Jobicy pipeline run finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

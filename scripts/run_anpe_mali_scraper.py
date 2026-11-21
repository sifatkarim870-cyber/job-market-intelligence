"""Manual entry point to run the ANPE Mali pipeline end-to-end.

Fetches, parses, validates, cleans, and persists the agency's job listings
into PostgreSQL, logging scraping sessions and performing change detection
via content hashing. Mirrors ``run_anpe_bf_scraper.py``'s main run path;
discovery is a keyless WP Job Manager REST ``job-listings`` query.

Usage:
    python scripts/run_anpe_mali_scraper.py [--no-db]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.anpe_mali import AnpeMaliError, AnpeMaliPipeline


def main() -> int:
    """Run the ANPE Mali pipeline and print a readable summary."""
    parser = argparse.ArgumentParser(description="ANPE Mali Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Run fetch, parse, validate, and clean steps without persisting to PostgreSQL.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    pipeline = AnpeMaliPipeline()
    store_db = not args.no_db

    logger.info("Starting ANPE Mali pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except AnpeMaliError as exc:
        logger.error("ANPE Mali pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("ANPE MALI PIPELINE - RUN SUMMARY")
    print("=" * 70)
    print(f"Raw job records fetched: {run_result.raw_count}")
    print(f"Successfully parsed:     {run_result.parsed_count}")
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

    logger.info("ANPE Mali pipeline run finished successfully.")
    return runner_exit_code(run_result, store_db=store_db)


if __name__ == "__main__":
    raise SystemExit(main())

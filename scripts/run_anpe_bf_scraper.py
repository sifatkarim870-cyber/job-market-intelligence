"""Manual entry point to run the ANPE Burkina Faso pipeline end-to-end.

Fetches, parses, validates, cleans, and persists the agency's recruitment
notices into PostgreSQL, logging scraping sessions and performing change
detection via content hashing. Mirrors ``run_timesjobs_in_scraper.py``'s
main run path; discovery is a keyless WordPress REST posts query.

Usage:
    python scripts/run_anpe_bf_scraper.py [--no-db]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.common.runner import runner_exit_code
from job_market_intel.scrapers.anpe_bf import AnpeBfError, AnpeBfPipeline


def main() -> int:
    """Run the ANPE Burkina Faso pipeline and print a readable summary."""
    parser = argparse.ArgumentParser(description="ANPE Burkina Faso Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Run fetch, parse, validate, and clean steps without persisting to PostgreSQL.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    pipeline = AnpeBfPipeline()
    store_db = not args.no_db

    logger.info("Starting ANPE Burkina Faso pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except AnpeBfError as exc:
        logger.error("ANPE Burkina Faso pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("ANPE BURKINA FASO PIPELINE - RUN SUMMARY")
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

    logger.info("ANPE Burkina Faso pipeline run finished successfully.")
    return runner_exit_code(run_result, store_db=store_db)


if __name__ == "__main__":
    raise SystemExit(main())

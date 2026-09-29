"""Manual entry point to run the Reed automated pipeline end-to-end.

Fetches (Search, paginated, then Details per selected job), parses,
validates, cleans, and persists Reed job listings into PostgreSQL,
logging scraping sessions and performing change detection via content
hashing. Mirrors ``run_remotive_scraper.py``'s shape for the main run
path, with one addition: the run summary reports what happened to every
job Search found (processed / deferred / Details-failed), not just how
many made it all the way through — see
``scrapers/reed/pipeline.py``'s module docstring for why that breakdown
exists.

Real runs claim their queries from ops.reed_search_queue (seed it with
scripts/seed_reed_queries.py). Dry runs (--no-db) use the single
placeholder query and never touch the database.

Usage:
    python scripts/run_reed_scraper.py [--no-db]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.reed import ReedError, ReedPipeline


def main() -> int:
    """Run the Reed pipeline end-to-end and print a human-readable summary.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the scrape failed.
    """
    parser = argparse.ArgumentParser(description="Reed Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Run fetch, parse, validate, and clean steps without persisting to PostgreSQL.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    # ReedSettings() reads REED_API_KEY from the environment/.env at
    # construction time inside ReedPipeline() below -- raises immediately
    # with a clear error if it's not set, rather than making requests
    # Reed would reject. See scrapers/reed/config.py's module docstring.
    pipeline = ReedPipeline()
    store_db = not args.no_db

    if not store_db:
        print("-" * 70)
        print("DRY RUN: using the single placeholder query (no database access).")
        print("Real runs claim queries from ops.reed_search_queue instead --")
        print("seed it first with: python scripts/seed_reed_queries.py")
        print("-" * 70)
        print()

    logger.info("Starting Reed pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except ReedError as exc:
        logger.error("Reed pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("REED PIPELINE — RUN SUMMARY")
    print("=" * 70)
    print(f"Queries searched:            {run_result.queries_searched}")
    print(f"Unique jobs found (Search):  {run_result.raw_count}")
    print(f"Selected for processing:     {run_result.processed_count}")
    print(f"Deferred to next run (cap):  {run_result.deferred_count}")
    print(f"Details fetch failed:        {run_result.details_fetch_failed_count}")
    print(f"Successfully parsed:         {run_result.parsed_count}")
    print(f"Cleaned & normalized:        {run_result.cleaned_count}")
    print(f"Batch validation:            {'PASSED' if run_result.validation_passed else 'FAILED'}")
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

    logger.info("Reed pipeline run finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Manual entry point to run the Arbeitnow pipeline end-to-end.

Fetches the feed, parses, validates, cleans and persists postings into
PostgreSQL, logging the scraping session and performing change detection via
content hashing. Mirrors ``run_remotive_scraper.py``.

Supports ``--no-db`` (fetch/parse/validate/clean only) and ``--dsn`` to choose
the target database explicitly.

Usage:
    python scripts/run_arbeitnow_scraper.py --no-db
    python scripts/run_arbeitnow_scraper.py --dsn <local dsn>
"""

from __future__ import annotations

import argparse
import os

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.arbeitnow import ArbeitnowPipeline, ArbeitnowSettings


def main() -> int:
    """Run the Arbeitnow pipeline end-to-end and print a summary."""
    parser = argparse.ArgumentParser(description="Arbeitnow Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Run fetch, parse, validate and clean without persisting to PostgreSQL.",
    )
    parser.add_argument(
        "--dsn",
        help=(
            "Target database. IMPORTANT: without this the scraper writes to "
            "DATABASE_URL, which .env points at NEON -- not the laptop. "
            "LOCAL_DATABASE_URL exists in .env but no code reads it, so a plain "
            "run silently inserts into the wrong database."
        ),
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Cap on postings persisted this run.",
    )
    args = parser.parse_args()

    if args.dsn:
        # Set before anything calls get_database_config(), which reads the
        # environment at call time.
        os.environ["DATABASE_URL"] = args.dsn

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    overrides: dict = {}
    if args.max_jobs:
        overrides["max_jobs_per_run"] = args.max_jobs
    gh = ArbeitnowSettings(**overrides) if overrides else ArbeitnowSettings()

    pipeline = ArbeitnowPipeline(settings=gh)
    store_db = not args.no_db

    logger.info("Starting Arbeitnow pipeline (store_db={}).", store_db)
    try:
        result = pipeline.run(store_db=store_db)
    except Exception as exc:  # noqa: BLE001 - surfaced as a run summary, not a traceback
        logger.error("Arbeitnow pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("ARBEITNOW PIPELINE - RUN SUMMARY")
    print("=" * 70)
    print(f"Raw records fetched:   {result.raw_count}")
    print(f"Successfully parsed:   {result.parsed_count}")
    print(f"Cleaned & normalized:  {result.cleaned_count}")
    print(f"Batch validation:      {'PASSED' if result.validation_passed else 'FAILED'}")
    if result.issues:
        print("Issues:")
        for issue in result.issues[:10]:
            print(f"  - {issue}")
        if len(result.issues) > 10:
            print(f"  ... and {len(result.issues) - 10} more")
    print()
    if store_db:
        print("DATABASE PERSISTENCE & DEDUPLICATION:")
        print(f"  New jobs inserted:   {result.inserted_count}")
        print(f"  Jobs updated:        {result.updated_count}")
        print(f"  Jobs unchanged:      {result.unchanged_count}")
        print(f"  Persistence failures:{result.failed_count}")
    else:
        print("DRY-RUN MODE (--no-db active): Database storage skipped.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

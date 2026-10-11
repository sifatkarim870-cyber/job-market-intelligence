"""Manual entry point to run the Greenhouse pipeline end-to-end.

Fetches every configured company board, parses, validates, cleans and
persists postings into PostgreSQL, logging the scraping session and performing
change detection via content hashing. Mirrors ``run_remotive_scraper.py``.

Supports ``--no-db`` (fetch/parse/validate/clean only) and ``--boards`` to
target specific slugs for a one-off.

Usage:
    python scripts/run_greenhouse_scraper.py --no-db
    python scripts/run_greenhouse_scraper.py --boards gitlab,stripe
    python scripts/run_greenhouse_scraper.py --dsn <local dsn>
"""

from __future__ import annotations

import argparse
import os

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.greenhouse import (
    GreenhousePipeline,
    GreenhouseSettings,
)


def main() -> int:  # noqa: C901 - a flat CLI surface
    """Run the Greenhouse pipeline end-to-end and print a summary."""
    parser = argparse.ArgumentParser(description="Greenhouse Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Run fetch, parse, validate and clean without persisting to PostgreSQL.",
    )
    parser.add_argument(
        "--boards",
        help="Comma-separated board slugs to scrape, overriding the configured list.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Cap on postings persisted this run, across all boards.",
    )
    parser.add_argument(
        "--dsn",
        help=(
            "Target database. IMPORTANT: without this the scraper writes to "
            "DATABASE_URL, which .env points at NEON -- not the laptop. "
            "LOCAL_DATABASE_URL exists in .env but no code reads it, so a plain "
            "run silently inserts into Neon."
        ),
    )
    args = parser.parse_args()

    if args.dsn:
        # CI_DATABASE_URL, not DATABASE_URL.
        #
        # db.target.resolve_dsn() consults CI_DATABASE_URL first precisely so a
        # scraper never has to repoint the environment, and this used to set
        # DATABASE_URL instead. That is invisible while the two agree and
        # actively wrong when they do not: with --dsn absent and an unset
        # secret, the workflow still exports DATABASE_URL="" (GitHub renders an
        # unset secret as the empty string), so the resolver fell through to
        # "no configuration" and the run died with
        #   No database configuration found.
        # Overwriting DATABASE_URL here also silently outranked the hosted DSN
        # whenever the two were configured differently.
        #
        # Set before anything calls get_database_config(), which reads the
        # environment at call time.
        os.environ["CI_DATABASE_URL"] = args.dsn

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    gh = GreenhouseSettings()
    overrides: dict = {}
    if args.boards:
        overrides["company_slugs"] = [s.strip() for s in args.boards.split(",") if s.strip()]
    if args.max_jobs:
        overrides["max_jobs_per_run"] = args.max_jobs
    if overrides:
        gh = GreenhouseSettings(**overrides)
        logger.info("using board override: {}", gh.company_slugs)

    pipeline = GreenhousePipeline(settings=gh)
    store_db = not args.no_db

    logger.info("Starting Greenhouse pipeline (store_db={}).", store_db)
    try:
        result = pipeline.run(store_db=store_db)
    except Exception as exc:  # noqa: BLE001 - surfaced as a run summary, not a traceback
        logger.error("Greenhouse pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("GREENHOUSE PIPELINE - RUN SUMMARY")
    print("=" * 70)
    print(f"Boards attempted:      {result.boards_attempted}")
    print(f"Boards failed:         {result.boards_failed}")
    for slug, reason in result.board_failures.items():
        print(f"   - {slug}: {reason}")
    print()
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

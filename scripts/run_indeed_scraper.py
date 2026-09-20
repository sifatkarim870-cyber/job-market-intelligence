"""Manual entry point to run one Indeed scraper pipeline cycle end-to-end.

Claims the next due (query, location) row from ops.scrape_query_queue, runs
a paced/capped Selenium session against it, validates, cleans, and (unless
--no-db) persists results into PostgreSQL — logging a scraping session and
recording the queue item's outcome for the next run to pick up from.

Usage:
    python scripts/run_indeed_scraper.py [--no-db]

Requires ops.scrape_query_queue to already have at least one row for
source 'indeed' — run scripts/seed_indeed_queries.py first if it's empty
(the pipeline logs a clear warning and exits cleanly, rather than failing,
if the queue has nothing eligible).
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.indeed import IndeedError, IndeedPipeline


def main() -> int:
    """Run the Indeed pipeline end-to-end and print a human-readable summary.

    Returns:
        Process exit code: ``0`` on success (including "queue was empty"
        and "session was blocked" — both are reported, not crashes), ``1``
        only on an unhandled ``IndeedError``.
    """
    parser = argparse.ArgumentParser(description="Indeed Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help=(
            "Run the browser session, validation, and cleaning steps without persisting to "
            "PostgreSQL. The queue item is still claimed (marked in_progress) even in this "
            "mode — see IndeedPipeline.run()'s docstring for why."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    pipeline = IndeedPipeline()
    store_db = not args.no_db

    logger.info("Starting Indeed pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except IndeedError as exc:
        logger.error("Indeed pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("INDEED PIPELINE — RUN SUMMARY")
    print("=" * 70)

    if run_result.queue_empty:
        print("Queue was empty — nothing eligible in ops.scrape_query_queue for 'indeed'.")
        print("Run scripts/seed_indeed_queries.py to add (query, location) combinations.")
        print("=" * 70)
        return 0

    print(f"Query worked:            {run_result.query_text!r} @ {run_result.location_text!r}")
    print(f"Search pages visited:    {run_result.search_pages_visited}")
    print(f"Detail pages visited:    {run_result.detail_pages_visited}")
    print(f"Raw cards extracted:     {run_result.raw_count}")
    print(f"Successfully parsed:     {run_result.parsed_count}")
    print(f"Cleaned & normalized:    {run_result.cleaned_count}")
    print(f"Batch validation:        {'PASSED' if run_result.validation_passed else 'FAILED'}")
    if run_result.issues:
        for issue in run_result.issues:
            print(f"  - {issue}")
    print()
    print(f"Queue outcome:           {run_result.queue_status}")
    if run_result.blocked_reason:
        print(f"  Blocked reason:        {run_result.blocked_reason}")
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

    logger.info("Indeed pipeline run finished (queue_status={}).", run_result.queue_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

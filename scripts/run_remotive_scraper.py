"""Manual entry point to run the Remotive automated pipeline end-to-end.

Fetches, parses, validates, cleans, and persists Remotive job listings into
PostgreSQL, logging scraping sessions and performing change detection via
content hashing. Mirrors ``run_remoteok_scraper.py``/``run_weworkremotely_scraper.py``
exactly for the main run path.

Also supports ``--inspect-shape``: a single, minimal live API call whose
only purpose is answering the one thing Step 18's code review couldn't
confirm from documentation alone — whether Remotive's live response
actually includes a ``tags`` field (see
``scrapers/remotive/models.py``'s module docstring for the full context).
This performs exactly one HTTP request, well within Remotive's documented
rate-limit guidance, and does not persist anything.

Usage:
    python scripts/run_remotive_scraper.py [--no-db]
    python scripts/run_remotive_scraper.py --inspect-shape
"""

from __future__ import annotations

import argparse
import json

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.remotive import RemotiveClient, RemotiveError, RemotivePipeline


def _inspect_shape() -> int:
    """Fetch one live page from Remotive and report on its actual field shape.

    Prints, in order: the top-level response keys, the first job record's
    raw keys, and an explicit yes/no on whether ``tags`` is present —
    directly answering the open question flagged throughout Step 18's
    code (models.py, cleaning/remotive_cleaner.py, validation/remotive_validator.py)
    rather than leaving it as a standing assumption.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the fetch failed.
    """
    print("Fetching one live page from Remotive to inspect the real response shape...")
    print("(This is a single HTTP request — well within Remotive's documented rate limit.)")
    print()

    client = RemotiveClient()
    try:
        raw_jobs = client.fetch_raw_jobs()
    except RemotiveError as exc:
        logger.error("Could not fetch from Remotive for shape inspection: {}", exc)
        return 1

    if not raw_jobs:
        print("Fetched zero job records — cannot inspect shape.")
        return 1

    sample = raw_jobs[0]

    print("=" * 70)
    print("REMOTIVE LIVE RESPONSE — SHAPE INSPECTION")
    print("=" * 70)
    print(f"Total job records in this response: {len(raw_jobs)}")
    print()
    print("First job record's raw keys:")
    for key in sample:
        print(f"  - {key}")
    print()

    has_tags = "tags" in sample
    print(f"'tags' field present on the first record: {has_tags}")
    if has_tags:
        print(f"  tags value: {sample['tags']!r}")
    else:
        print(
            "  -> Confirms the official README's example (no tags field). "
            "RawRemotiveJob.tags will stay an empty list for every job from "
            "this source until/unless that changes."
        )
    print()

    tags_present_count = sum(1 for job in raw_jobs if job.get("tags"))
    print(
        f"Records with a non-empty 'tags' value across this whole response: "
        f"{tags_present_count}/{len(raw_jobs)}"
    )
    print()
    print("Full first record (pretty-printed):")
    print(json.dumps(sample, indent=2, default=str))
    print("=" * 70)

    return 0


def main() -> int:
    """Run the Remotive pipeline end-to-end and print a human-readable summary.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the scrape failed.
    """
    parser = argparse.ArgumentParser(description="Remotive Job Intelligence Pipeline")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Run fetch, parse, validate, and clean steps without persisting to PostgreSQL.",
    )
    parser.add_argument(
        "--inspect-shape",
        action="store_true",
        help=(
            "Fetch one live page and report its actual field shape "
            "(specifically whether 'tags' is present), then exit "
            "without running the full pipeline or touching the database."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    if args.inspect_shape:
        return _inspect_shape()

    pipeline = RemotivePipeline()
    store_db = not args.no_db

    logger.info("Starting Remotive pipeline (store_db={}).", store_db)

    try:
        run_result = pipeline.run(store_db=store_db)
    except RemotiveError as exc:
        logger.error("Remotive pipeline run failed: {}", exc)
        return 1

    print()
    print("=" * 70)
    print("REMOTIVE PIPELINE — RUN SUMMARY")
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

    logger.info("Remotive pipeline run finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Manual entry point to run one Indeed scraper pipeline cycle end-to-end.

Claims the next due (query, location) row from ops.scrape_query_queue, runs
a paced/capped Selenium session against it, validates, cleans, and (unless
--no-db) persists results into PostgreSQL — logging a scraping session and
recording the queue item's outcome for the next run to pick up from.

Usage:
    python scripts/run_indeed_scraper.py [--no-db] [--summary-json PATH]

Requires ops.scrape_query_queue to already have at least one row for
source 'indeed' — run scripts/seed_indeed_queries.py first if it's empty
(the pipeline logs a clear warning and exits cleanly, rather than failing,
if the queue has nothing eligible).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.indeed import IndeedError, IndeedPipeline

# Outcome values written to the summary JSON.
#
# "blocked" is deliberately split from "partial" on whether anything was
# actually collected. A run that scrapes 16 jobs and is then challenged on the
# next page has worked, and counting that against the alerting threshold would
# fail builds that did their job — measured locally: 16 jobs over 2 search
# pages and 16 detail pages, validation passed, then a challenge on page 2.
# Only a run that collected *nothing* is the silent failure worth escalating.
OUTCOME_OK = "ok"
OUTCOME_EMPTY = "empty"
OUTCOME_BLOCKED = "blocked"
OUTCOME_PARTIAL = "partial"
OUTCOME_ERROR = "error"


def _classify_outcome(any_blocked: bool, jobs_inserted: int) -> str:
    """Whether this run collected nothing, collected something, or was stopped
    by a challenge.

    Split on ``jobs_inserted`` rather than on "was there a block" so that a run
    which did real work before being challenged is not reported as the silent
    zero-job failure the alerting exists to catch.
    """
    if not any_blocked:
        return OUTCOME_OK
    return OUTCOME_PARTIAL if jobs_inserted > 0 else OUTCOME_BLOCKED


def _write_summary(path: Path | None, payload: dict[str, Any]) -> None:
    """Best-effort machine-readable run outcome for CI to act on.

    Never raises: a missing summary must not turn a scrape into a crash. When
    it is absent the workflow treats the run as "unknown" and does not count it
    against the consecutive-block threshold, because guessing "not blocked"
    from a file that failed to write would silently disarm the alerting.
    """
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write run summary to {}: {}", path, exc)


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
    parser.add_argument(
        "--summary-json",
        metavar="PATH",
        help=(
            "Write a machine-readable summary of this run (outcome, rows worked, jobs "
            "inserted, block reasons, whether a proxy was used) to PATH. Read by CI to "
            "tell a real scrape apart from a silent block, which both exit 0."
        ),
    )
    args = parser.parse_args()
    summary_path = Path(args.summary_json) if args.summary_json else None

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    pipeline = IndeedPipeline()
    store_db = not args.no_db

    logger.info("Starting Indeed pipeline (store_db={}).", store_db)

    try:
        run_results = pipeline.run(store_db=store_db)
    except IndeedError as exc:
        logger.error("Indeed pipeline run failed: {}", exc)
        _write_summary(summary_path, {"outcome": OUTCOME_ERROR, "error": str(exc)})
        return 1

    if run_results[0].queue_empty:
        _write_summary(
            summary_path,
            {"outcome": OUTCOME_EMPTY, "rows_worked": 0, "jobs_inserted": 0},
        )

    print()
    print("=" * 70)
    print("INDEED PIPELINE — RUN SUMMARY")
    print("=" * 70)

    if run_results[0].queue_empty:
        print("Queue was empty — nothing eligible in ops.scrape_query_queue for 'indeed'.")
        print("Run scripts/seed_indeed_queries.py to add (query, location) combinations.")
        print("=" * 70)
        return 0

    total_inserted = sum(r.inserted_count for r in run_results)
    total_updated = sum(r.updated_count for r in run_results)
    total_unchanged = sum(r.unchanged_count for r in run_results)
    total_failed = sum(r.failed_count for r in run_results)
    blocked_reasons = [r.blocked_reason for r in run_results if r.blocked_reason]
    any_blocked = bool(blocked_reasons)

    _write_summary(
        summary_path,
        {
            "outcome": _classify_outcome(any_blocked, total_inserted),
            "rows_worked": len(run_results),
            "jobs_inserted": total_inserted,
            "jobs_updated": total_updated,
            "search_pages_visited": sum(r.search_pages_visited for r in run_results),
            "detail_pages_visited": sum(r.detail_pages_visited for r in run_results),
            "blocked_reasons": blocked_reasons,
            "proxy_used": bool(pipeline.settings.proxy_server),
        },
    )

    print(f"Queue items worked:          {len(run_results)}")
    for run_result in run_results:
        print(
            f"  - {run_result.query_text!r} @ {run_result.location_text!r}"
            f" — {run_result.search_pages_visited} search pages,"
            f" {run_result.detail_pages_visited} detail pages,"
            f" {run_result.raw_count} cards, queue_status={run_result.queue_status}"
        )
        if run_result.blocked_reason:
            print(f"      Blocked reason:        {run_result.blocked_reason}")
    all_passed = all(r.validation_passed for r in run_results)
    print(f"Batch validation:            {'PASSED' if all_passed else 'FAILED'}")
    for run_result in run_results:
        for issue in run_result.issues:
            print(f"  - {issue}")
    print()
    if store_db:
        print("DATABASE PERSISTENCE & DEDUPLICATION:")
        print(f"  New jobs inserted:     {total_inserted}")
        print(f"  Jobs updated:          {total_updated}")
        print(f"  Jobs unchanged:        {total_unchanged}")
        print(f"  Persistence failures:  {total_failed}")
    else:
        print("DRY-RUN MODE (--no-db active): Database storage skipped.")
    print("=" * 70)

    if any_blocked:
        logger.warning("Indeed run stopped early on a controlled block — see summary above.")
    logger.info("Indeed pipeline run finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

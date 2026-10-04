"""scheduler.jobs
===============

The actual scheduled job function(s). Kept separate from ``service.py``
(which wires a job to a trigger and an APScheduler instance) so the job
logic itself is a plain, trivially unit-testable function that doesn't
need a real scheduler running to test.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.indeed import IndeedError, IndeedPipeline
from job_market_intel.scrapers.remoteok import RemoteOKError, RemoteOKPipeline


def run_remoteok_pipeline_job() -> None:
    """Scheduled entry point: run the RemoteOK pipeline once and log the outcome.

    Never raises. A single failed run (network blip, transient DB issue, a
    RemoteOK feed hiccup) must not take down the scheduler process itself -
    the next scheduled run should still fire in ``scrape_interval_hours``.
    This mirrors the same log-and-continue philosophy already used
    throughout the pipeline (``RemoteOKParser``, ``RemoteOKCleaner``,
    ``JobRepository.save_cleaned_jobs``): one bad record, or one bad run,
    should never take down everything after it.

    A fresh ``RemoteOKPipeline`` is constructed on every call (matching
    ``scripts/run_remoteok_scraper.py``'s manual-run pattern) rather than
    reused across scheduled runs, so each run starts from clean settings
    and a clean HTTP client with no state carried over from the previous
    run.
    """
    logger.info("Scheduled RemoteOK pipeline run starting.")
    try:
        pipeline = RemoteOKPipeline()
        result = pipeline.run(store_db=True)
    except RemoteOKError as exc:
        logger.error("Scheduled RemoteOK pipeline run failed: {}", exc)
        return
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        logger.error("Scheduled RemoteOK pipeline run failed unexpectedly: {}", exc)
        return

    logger.info(
        "Scheduled RemoteOK pipeline run complete: {} inserted, {} updated, "
        "{} unchanged, {} failed (session_id={}).",
        result.inserted_count,
        result.updated_count,
        result.unchanged_count,
        result.failed_count,
        result.session_id,
    )
    if not result.validation_passed:
        logger.warning(
            "Scheduled run completed but batch validation flagged issues: {}",
            result.issues,
        )


def run_indeed_pipeline_job() -> None:
    """Scheduled entry point: run the Indeed pipeline once and log the outcome.

    Same never-raises contract as ``run_remoteok_pipeline_job`` above, and
    for the same reason - one bad run (a block, a driver crash, a transient
    DB issue) must not take down the scheduler process, since the whole
    point of this scraper is running unattended for years.

    Unlike RemoteOK's job, a "successful" run here isn't automatically
    good news at the INFO level: a non-None ``blocked_reason`` means the
    session hit ``IndeedBlockedError`` (a detected challenge, or too many
    consecutive fetch failures - see ``scrapers/indeed/pipeline.py``) and
    stopped itself cleanly, exactly as designed. That's not a bug and
    shouldn't look like one in the logs, but it's also not routine
    "nothing to see here" news either - logged at WARNING so it's visible
    in a scan of scheduler logs without being mistaken for a Python
    exception. Note this is *not* signalled by queue_status: a blocked
    row is left 'pending' so it stays claimable, so queue_status is
    "pending" both for a block and for an ordinary page-cap stop, and
    ``blocked_reason`` is what actually distinguishes them.
    ``queue_empty`` (nothing left in ``ops.scrape_query_queue``
    to claim) is logged as its own distinct, calmer case - it means the
    scraper is idle for a legitimate reason, not that anything went wrong.

    A fresh ``IndeedPipeline`` is constructed on every call, matching both
    ``run_remoteok_pipeline_job``'s pattern above and
    ``scripts/run_indeed_scraper.py``'s manual-run pattern - each run gets
    its own browser session lifecycle from a clean slate, never a session
    reused across scheduled runs.
    """
    logger.info("Scheduled Indeed pipeline run starting.")
    try:
        pipeline = IndeedPipeline()
        results = pipeline.run(store_db=True)
    except IndeedError as exc:
        logger.error("Scheduled Indeed pipeline run failed: {}", exc)
        return
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        logger.error("Scheduled Indeed pipeline run failed unexpectedly: {}", exc)
        return

    if results[0].queue_empty:
        logger.info(
            "Scheduled Indeed pipeline run found nothing eligible in "
            "ops.scrape_query_queue - idle this cycle, not an error."
        )
        return

    total_inserted = sum(r.inserted_count for r in results)
    total_updated = sum(r.updated_count for r in results)
    total_unchanged = sum(r.unchanged_count for r in results)
    total_failed = sum(r.failed_count for r in results)
    # Keyed off blocked_reason, not queue_status: a blocked row is left
    # 'pending' so it can be retried, so queue_status no longer identifies
    # blocks (and 'pending' also means an ordinary page-cap stop).
    blocked = next((r for r in results if r.blocked_reason is not None), None)

    logger.info(
        "Scheduled Indeed pipeline run complete: {} item(s) worked, "
        "{} inserted, {} updated, {} unchanged, {} failed.",
        len(results),
        total_inserted,
        total_updated,
        total_unchanged,
        total_failed,
    )
    for result in results:
        logger.debug(
            "  item: query={!r} location={!r} queue_status={} session_id={}",
            result.query_text,
            result.location_text,
            result.queue_status,
            result.session_id,
        )
    if blocked is not None:
        logger.warning(
            "Scheduled Indeed run stopped early on a controlled block, not a crash: {} "
            "(any remaining claimed items this run were released back to pending).",
            blocked.blocked_reason,
        )
    if any(not r.validation_passed for r in results):
        logger.warning(
            "Scheduled Indeed run completed but at least one item's batch validation "
            "flagged issues — see per-item debug logs above."
        )

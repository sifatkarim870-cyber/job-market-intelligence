"""scheduler.jobs
===============

The actual scheduled job function(s). Kept separate from ``service.py``
(which wires a job to a trigger and an APScheduler instance) so the job
logic itself is a plain, trivially unit-testable function that doesn't
need a real scheduler running to test.
"""

from __future__ import annotations

from loguru import logger

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

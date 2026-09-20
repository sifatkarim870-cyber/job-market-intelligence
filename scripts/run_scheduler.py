"""Entry point to run the RemoteOK and Indeed pipeline schedulers.

Starts a long-running process that runs BOTH pipelines automatically on
their own fixed intervals - every 12 hours each by default, configurable
via SCHEDULER_SCRAPE_INTERVAL_HOURS (RemoteOK) and
SCHEDULER_INDEED_SCRAPE_INTERVAL_HOURS (Indeed) in .env. Leave this
running in a terminal (or, once Step 31/Docker or a service manager is in
place, as a background service so it survives reboots).

Worth knowing before leaving this running unattended: with default
settings, starting this process immediately fires both pipelines once
(run_immediately_on_start=True) - including a real Indeed browser session.
Indeed's own scraper defaults to a VISIBLE (non-headless) browser window
by design (see scrapers/indeed/config.py's docstring on why), so running
this as a true background/headless service requires either setting
INDEED_HEADLESS=true in .env or ensuring a display/virtual display is
available wherever this process runs.

Usage:
    python scripts/run_scheduler.py
    python scripts/run_scheduler.py --run-once
    python scripts/run_scheduler.py --run-once-indeed
    python scripts/run_scheduler.py --interval-hours 0.05
    python scripts/run_scheduler.py --indeed-interval-hours 0.1
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scheduler import (
    SchedulerSettings,
    build_scheduler,
    run_indeed_pipeline_job,
    run_remoteok_pipeline_job,
)


def main() -> int:
    """Parse CLI args and either run one pipeline once, or start the
    recurring scheduler for both.

    Returns:
        Process exit code: always ``0`` - a failed individual pipeline run
        is already logged and swallowed inside the job functions (see
        their docstrings for why), so there is nothing for this process
        itself to treat as a fatal exit condition short of a Ctrl+C.
    """
    parser = argparse.ArgumentParser(description="RemoteOK + Indeed Pipeline Scheduler")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help=(
            "Run the RemoteOK pipeline exactly once and exit, instead of "
            "starting the recurring scheduler. Useful for smoke-testing this "
            "setup, or if you'd rather trigger runs externally (Windows Task "
            "Scheduler, cron, etc.) than leave this process running."
        ),
    )
    parser.add_argument(
        "--run-once-indeed",
        action="store_true",
        help=(
            "Same as --run-once, but for the Indeed pipeline. Can be combined "
            "with --run-once to run both once and exit."
        ),
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=None,
        help=(
            "Override SCHEDULER_SCRAPE_INTERVAL_HOURS (RemoteOK) for this run "
            "only (does not modify .env). Handy for a quick manual test, e.g. "
            "--interval-hours 0.05 for a run roughly every 3 minutes."
        ),
    )
    parser.add_argument(
        "--indeed-interval-hours",
        type=float,
        default=None,
        help=(
            "Override SCHEDULER_INDEED_SCRAPE_INTERVAL_HOURS for this run only "
            "(does not modify .env)."
        ),
    )
    args = parser.parse_args()

    app_settings = get_settings()
    configure_logging(
        log_dir="logs/scheduler", console_level=app_settings.log_level, file_level="DEBUG"
    )

    if args.run_once or args.run_once_indeed:
        if args.run_once:
            logger.info("Running the RemoteOK pipeline once (--run-once) and exiting.")
            run_remoteok_pipeline_job()
        if args.run_once_indeed:
            logger.info("Running the Indeed pipeline once (--run-once-indeed) and exiting.")
            run_indeed_pipeline_job()
        return 0

    scheduler_settings = SchedulerSettings()
    overrides: dict[str, float] = {}
    if args.interval_hours is not None:
        overrides["scrape_interval_hours"] = args.interval_hours
    if args.indeed_interval_hours is not None:
        overrides["indeed_scrape_interval_hours"] = args.indeed_interval_hours
    if overrides:
        scheduler_settings = scheduler_settings.model_copy(update=overrides)

    scheduler = build_scheduler(scheduler_settings)
    logger.info("Scheduler starting. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested; stopping scheduler.")
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

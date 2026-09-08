"""Entry point to run the RemoteOK pipeline scheduler (Step 12).

Starts a long-running process that runs the RemoteOK pipeline
automatically on a fixed interval - every 12 hours by default,
configurable via SCHEDULER_SCRAPE_INTERVAL_HOURS in .env. Leave this
running in a terminal (or, once Step 31/Docker or a service manager is in
place, as a background service so it survives reboots).

Usage:
    python scripts/run_scheduler.py
    python scripts/run_scheduler.py --run-once
    python scripts/run_scheduler.py --interval-hours 0.05
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.scheduler import (
    SchedulerSettings,
    build_scheduler,
    run_remoteok_pipeline_job,
)


def main() -> int:
    """Parse CLI args and either run once or start the recurring scheduler.

    Returns:
        Process exit code: always ``0`` - a failed individual pipeline run
        is already logged and swallowed inside ``run_remoteok_pipeline_job``
        (see its docstring for why), so there is nothing for this process
        itself to treat as a fatal exit condition short of a Ctrl+C.
    """
    parser = argparse.ArgumentParser(description="RemoteOK Pipeline Scheduler")
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
        "--interval-hours",
        type=float,
        default=None,
        help=(
            "Override SCHEDULER_SCRAPE_INTERVAL_HOURS for this run only "
            "(does not modify .env). Handy for a quick manual test, e.g. "
            "--interval-hours 0.05 for a run roughly every 3 minutes."
        ),
    )
    args = parser.parse_args()

    app_settings = get_settings()
    configure_logging(
        log_dir="logs/scheduler", console_level=app_settings.log_level, file_level="DEBUG"
    )

    if args.run_once:
        logger.info("Running the RemoteOK pipeline once (--run-once) and exiting.")
        run_remoteok_pipeline_job()
        return 0

    scheduler_settings = SchedulerSettings()
    if args.interval_hours is not None:
        scheduler_settings = scheduler_settings.model_copy(
            update={"scrape_interval_hours": args.interval_hours}
        )

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

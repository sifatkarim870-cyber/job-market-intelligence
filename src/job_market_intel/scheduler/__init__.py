"""Automated scheduling for the RemoteOK pipeline (Step 12).

This package owns exactly one concern: running ``RemoteOKPipeline`` on a
fixed interval, unattended, as its own long-running process. It does not
touch scraping, cleaning, validation, or storage logic itself - all of
that already exists in ``scrapers.remoteok``, ``cleaning``, ``validation``,
and ``db``. This package only decides *when* that existing pipeline runs.

Typical usage (see ``scripts/run_scheduler.py`` for the full CLI):

    from job_market_intel.scheduler import build_scheduler

    scheduler = build_scheduler()
    scheduler.start()  # blocks; runs the RemoteOK pipeline on schedule
"""

from .config import SchedulerSettings
from .jobs import run_remoteok_pipeline_job
from .service import build_scheduler

__all__ = [
    "SchedulerSettings",
    "run_remoteok_pipeline_job",
    "build_scheduler",
]

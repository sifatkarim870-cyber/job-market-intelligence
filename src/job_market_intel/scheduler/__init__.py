"""Automated scheduling for the RemoteOK and Indeed pipelines (Step 12;
extended to add Indeed).

This package owns exactly one concern: running ``RemoteOKPipeline`` and
``IndeedPipeline`` each on their own fixed interval, unattended, as one
long-running process. It does not touch scraping, cleaning, validation,
or storage logic itself - all of that already exists in
``scrapers.remoteok``, ``scrapers.indeed``, ``cleaning``, ``validation``,
and ``db``. This package only decides *when* those existing pipelines run.

Typical usage (see ``scripts/run_scheduler.py`` for the full CLI):

    from job_market_intel.scheduler import build_scheduler

    scheduler = build_scheduler()
    scheduler.start()  # blocks; runs both pipelines on their own schedules
"""

from .config import SchedulerSettings
from .jobs import run_indeed_pipeline_job, run_remoteok_pipeline_job
from .service import INDEED_JOB_ID, REMOTEOK_JOB_ID, build_scheduler

__all__ = [
    "SchedulerSettings",
    "run_remoteok_pipeline_job",
    "run_indeed_pipeline_job",
    "build_scheduler",
    "REMOTEOK_JOB_ID",
    "INDEED_JOB_ID",
]

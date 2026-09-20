"""scheduler.service
==================

Builds a configured APScheduler instance that runs the RemoteOK and
Indeed pipelines on their own fixed intervals (Step 12; extended here to
add Indeed).

Why BlockingScheduler, not BackgroundScheduler: this module is meant to
be the entire content of its own long-running process, started via
``scripts/run_scheduler.py`` and left running (in a terminal, or later
under Windows Task Scheduler / NSSM / a Docker container once Step 31
happens) - not a component embedded inside another event loop or web
server. ``BlockingScheduler.start()`` takes over the calling thread,
which is exactly the "run forever until stopped" behavior a standalone
scheduler process needs. If Step 34's FastAPI service later wants to
trigger scrapes itself from inside the API process, ``BackgroundScheduler``
is the right choice there instead - swap it in without touching
``jobs.py`` at all, since the job function itself has no idea which kind
of scheduler is calling it.

Why UTC: an interval trigger computes "next run = previous run + interval"
using the scheduler's own clock. A local timezone with DST would make
that arithmetic ambiguous twice a year (an 11-hour or 13-hour gap instead
of 12, right around the clock change). UTC has no DST, so a 12-hour
interval is always exactly 12 hours, regardless of where the machine
running this is physically located or how its OS timezone is configured.

Two independent jobs, one scheduler: RemoteOK and Indeed are registered
as two separate APScheduler jobs, each with its own id and its own
interval trigger (see ``SchedulerSettings.scrape_interval_hours`` /
``indeed_scrape_interval_hours``) rather than one combined job that runs
both pipelines back to back. Kept independent deliberately - they have
nothing in common operationally (different sites, wildly different
per-run duration: RemoteOK's HTTP fetch finishes in seconds, Indeed's
paced browser session takes minutes), and a slow/blocked Indeed run must
never delay or skip a RemoteOK run that was due in the meantime, or vice
versa. ``max_instances=1`` on each job independently prevents that
specific job from overlapping with itself, which matters most for
Indeed: two simultaneous browser sessions would double real traffic to
Indeed at once, working directly against the "stay unremarkable" pacing
this scraper was built around.
"""

from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from job_market_intel.scheduler.config import SchedulerSettings
from job_market_intel.scheduler.jobs import run_indeed_pipeline_job, run_remoteok_pipeline_job

REMOTEOK_JOB_ID = "remoteok_pipeline"
INDEED_JOB_ID = "indeed_pipeline"


def _common_job_kwargs(settings: SchedulerSettings) -> dict[str, object]:
    """Kwargs shared by both jobs' add_job() calls.

    IMPORTANT: `next_run_time` is only included when an immediate first
    run is wanted. Explicitly passing `next_run_time=None` is NOT
    equivalent to omitting the argument - APScheduler treats an explicit
    `None` as "add this job in a paused state, with no next run scheduled
    at all" rather than "compute the next run from the trigger as usual."
    Omitting the kwarg entirely is what produces the correct "wait one
    interval, then fire" behavior. Verified empirically against
    apscheduler 3.11.3 before relying on it.
    """
    kwargs: dict[str, object] = {
        "misfire_grace_time": settings.misfire_grace_time_seconds,
        "coalesce": settings.coalesce_missed_runs,
        "max_instances": 1,
        "replace_existing": True,
    }
    if settings.run_immediately_on_start:
        kwargs["next_run_time"] = datetime.now(UTC)
    return kwargs


def build_scheduler(settings: SchedulerSettings | None = None) -> BlockingScheduler:
    """Construct a BlockingScheduler with the RemoteOK and Indeed pipeline
    jobs registered.

    Does not start the scheduler - call ``.start()`` on the returned
    object (typically from ``scripts/run_scheduler.py``) once you're
    ready to block the process and begin running scheduled jobs.

    Args:
        settings: Scheduling configuration. If omitted, ``SchedulerSettings()``
            is constructed with its defaults (and any ``SCHEDULER_``-prefixed
            overrides present in the environment/``.env`` file).
    """
    settings = settings or SchedulerSettings()
    scheduler = BlockingScheduler(timezone=UTC)

    scheduler.add_job(
        run_remoteok_pipeline_job,
        trigger=IntervalTrigger(hours=settings.scrape_interval_hours, timezone=UTC),
        id=REMOTEOK_JOB_ID,
        name="RemoteOK pipeline run",
        **_common_job_kwargs(settings),
    )

    scheduler.add_job(
        run_indeed_pipeline_job,
        trigger=IntervalTrigger(hours=settings.indeed_scrape_interval_hours, timezone=UTC),
        id=INDEED_JOB_ID,
        name="Indeed pipeline run",
        **_common_job_kwargs(settings),
    )

    logger.info(
        "Scheduler configured: RemoteOK every {} hour(s), Indeed every {} hour(s) "
        "(first run: {}, misfire grace: {}s, coalesce missed runs: {}).",
        settings.scrape_interval_hours,
        settings.indeed_scrape_interval_hours,
        "immediately" if settings.run_immediately_on_start else "after first interval",
        settings.misfire_grace_time_seconds,
        settings.coalesce_missed_runs,
    )
    return scheduler

"""Unit tests for job_market_intel.scheduler.service.build_scheduler.

What these tests verify, and why each matters:
    - Exactly two jobs are registered (RemoteOK and Indeed, each under
      its own expected job id), each running its own pipeline function on
      its own configured interval. This test file originally asserted
      "exactly one job" throughout, back when RemoteOK was the only
      scheduled pipeline - those assertions are updated here to "exactly
      two," not left as stale leftovers now that Indeed shares the same
      scheduler.
    - misfire_grace_time, coalesce, and max_instances are wired through
      from SchedulerSettings onto BOTH jobs, not just logged and
      forgotten.
    - Each job's interval is controlled independently by its own
      SchedulerSettings field (scrape_interval_hours for RemoteOK,
      indeed_scrape_interval_hours for Indeed) - changing one must never
      affect the other.
    - run_immediately_on_start controls whether BOTH jobs have a
      next_run_time set at all before the scheduler starts. This is
      deliberately tested via hasattr() rather than reading
      .next_run_time directly and comparing to None: APScheduler does
      not set that attribute at all on a freshly-added job that has no
      explicit next_run_time (it raises AttributeError on access until
      the scheduler starts and computes it from the trigger) - so
      hasattr() is the correct check, verified empirically against
      apscheduler 3.11.3, rather than an assumption about its internals.
"""

from __future__ import annotations

from datetime import timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from job_market_intel.scheduler.config import SchedulerSettings
from job_market_intel.scheduler.jobs import run_indeed_pipeline_job, run_remoteok_pipeline_job
from job_market_intel.scheduler.service import INDEED_JOB_ID, REMOTEOK_JOB_ID, build_scheduler


def _job_by_id(scheduler: BlockingScheduler, job_id: str):
    jobs = {job.id: job for job in scheduler.get_jobs()}
    return jobs[job_id]


class TestBuildScheduler:
    def test_returns_a_blocking_scheduler(self) -> None:
        assert isinstance(build_scheduler(SchedulerSettings()), BlockingScheduler)

    def test_registers_exactly_two_jobs_with_expected_ids(self) -> None:
        scheduler = build_scheduler(SchedulerSettings())
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert job_ids == {REMOTEOK_JOB_ID, INDEED_JOB_ID}

    def test_remoteok_job_runs_the_remoteok_pipeline_function(self) -> None:
        scheduler = build_scheduler(SchedulerSettings())
        assert _job_by_id(scheduler, REMOTEOK_JOB_ID).func is run_remoteok_pipeline_job

    def test_indeed_job_runs_the_indeed_pipeline_function(self) -> None:
        scheduler = build_scheduler(SchedulerSettings())
        assert _job_by_id(scheduler, INDEED_JOB_ID).func is run_indeed_pipeline_job

    def test_remoteok_interval_matches_configured_hours(self) -> None:
        scheduler = build_scheduler(SchedulerSettings(scrape_interval_hours=6))
        trigger = _job_by_id(scheduler, REMOTEOK_JOB_ID).trigger
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval == timedelta(hours=6)

    def test_indeed_interval_matches_configured_hours(self) -> None:
        scheduler = build_scheduler(SchedulerSettings(indeed_scrape_interval_hours=8))
        trigger = _job_by_id(scheduler, INDEED_JOB_ID).trigger
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval == timedelta(hours=8)

    def test_intervals_are_independent_of_each_other(self) -> None:
        # Changing RemoteOK's interval must never affect Indeed's, or
        # vice versa - they're separate settings fields for exactly this
        # reason.
        scheduler = build_scheduler(
            SchedulerSettings(scrape_interval_hours=6, indeed_scrape_interval_hours=24)
        )
        assert _job_by_id(scheduler, REMOTEOK_JOB_ID).trigger.interval == timedelta(hours=6)
        assert _job_by_id(scheduler, INDEED_JOB_ID).trigger.interval == timedelta(hours=24)

    def test_misfire_and_coalesce_and_max_instances_wired_through_both_jobs(self) -> None:
        settings = SchedulerSettings(misfire_grace_time_seconds=120, coalesce_missed_runs=False)
        scheduler = build_scheduler(settings)
        for job_id in (REMOTEOK_JOB_ID, INDEED_JOB_ID):
            job = _job_by_id(scheduler, job_id)
            assert job.misfire_grace_time == 120
            assert job.coalesce is False
            assert job.max_instances == 1

    def test_run_immediately_on_start_true_sets_next_run_time_on_both_jobs(self) -> None:
        settings = SchedulerSettings(run_immediately_on_start=True)
        scheduler = build_scheduler(settings)
        for job_id in (REMOTEOK_JOB_ID, INDEED_JOB_ID):
            job = _job_by_id(scheduler, job_id)
            assert hasattr(job, "next_run_time")
            assert job.next_run_time is not None

    def test_run_immediately_on_start_false_leaves_next_run_time_unset_on_both_jobs(self) -> None:
        settings = SchedulerSettings(run_immediately_on_start=False)
        scheduler = build_scheduler(settings)
        for job_id in (REMOTEOK_JOB_ID, INDEED_JOB_ID):
            assert not hasattr(_job_by_id(scheduler, job_id), "next_run_time")

    def test_default_settings_used_when_none_provided(self) -> None:
        # Should not raise, and should still produce exactly two jobs.
        assert len(build_scheduler().get_jobs()) == 2

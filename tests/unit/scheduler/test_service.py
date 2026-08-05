"""Unit tests for job_market_intel.scheduler.service.build_scheduler.

What these tests verify, and why each matters:
    - Exactly one job is registered, under the expected job id, running
      run_remoteok_pipeline_job on the configured interval.
    - misfire_grace_time, coalesce, and max_instances are wired through
      from SchedulerSettings onto the actual APScheduler job, not just
      logged and forgotten.
    - run_immediately_on_start controls whether the job has a next_run_time
      set at all before the scheduler starts. This is deliberately tested
      via hasattr() rather than reading .next_run_time directly and
      comparing to None: APScheduler does not set that attribute at all
      on a freshly-added job that has no explicit next_run_time (it
      raises AttributeError on access until the scheduler starts and
      computes it from the trigger) - so hasattr() is the correct check,
      verified empirically against apscheduler 3.11.3, rather than an
      assumption about its internals.
"""

from __future__ import annotations

from datetime import timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from job_market_intel.scheduler.config import SchedulerSettings
from job_market_intel.scheduler.jobs import run_remoteok_pipeline_job
from job_market_intel.scheduler.service import REMOTEOK_JOB_ID, build_scheduler


class TestBuildScheduler:
    def test_returns_a_blocking_scheduler(self) -> None:
        assert isinstance(build_scheduler(SchedulerSettings()), BlockingScheduler)

    def test_registers_exactly_one_job_with_expected_id(self) -> None:
        scheduler = build_scheduler(SchedulerSettings())
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == REMOTEOK_JOB_ID

    def test_job_runs_the_remoteok_pipeline_function(self) -> None:
        scheduler = build_scheduler(SchedulerSettings())
        assert scheduler.get_jobs()[0].func is run_remoteok_pipeline_job

    def test_interval_matches_configured_hours(self) -> None:
        scheduler = build_scheduler(SchedulerSettings(scrape_interval_hours=6))
        trigger = scheduler.get_jobs()[0].trigger
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval == timedelta(hours=6)

    def test_misfire_and_coalesce_and_max_instances_wired_through(self) -> None:
        settings = SchedulerSettings(misfire_grace_time_seconds=120, coalesce_missed_runs=False)
        job = build_scheduler(settings).get_jobs()[0]
        assert job.misfire_grace_time == 120
        assert job.coalesce is False
        assert job.max_instances == 1

    def test_run_immediately_on_start_true_sets_next_run_time(self) -> None:
        settings = SchedulerSettings(run_immediately_on_start=True)
        job = build_scheduler(settings).get_jobs()[0]
        assert hasattr(job, "next_run_time")
        assert job.next_run_time is not None

    def test_run_immediately_on_start_false_leaves_next_run_time_unset(self) -> None:
        settings = SchedulerSettings(run_immediately_on_start=False)
        job = build_scheduler(settings).get_jobs()[0]
        assert not hasattr(job, "next_run_time")

    def test_default_settings_used_when_none_provided(self) -> None:
        # Should not raise, and should still produce exactly one job.
        assert len(build_scheduler().get_jobs()) == 1

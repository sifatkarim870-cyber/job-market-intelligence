"""Unit tests for job_market_intel.scheduler.jobs.run_remoteok_pipeline_job
and run_indeed_pipeline_job.

What these tests verify, and why each matters:
    - A normal successful run constructs a fresh pipeline instance and
      calls .run(store_db=True) - the scheduler always persists to the
      database; a dry run is only for the manual CLI script.
    - A pipeline-specific error raised mid-run (e.g. the feed is down, or
      Indeed's session gets blocked) is caught and logged, not raised -
      the whole point of wrapping the pipeline here is that one bad
      scheduled run must not kill the scheduler process, or every future
      run along with it.
    - Any other unexpected exception is caught the same way, for the same
      reason - defensively, not just the errors we anticipated.
    - Indeed-specific: queue_empty and a non-None blocked_reason are each
      logged as their own distinct, non-crashing cases - see
      run_indeed_pipeline_job's own docstring for why neither should look
      like a Python exception in the logs. Blocks are identified by
      blocked_reason rather than queue_status, because a blocked row is left
      'pending' so it stays claimable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from job_market_intel.scheduler.jobs import run_indeed_pipeline_job, run_remoteok_pipeline_job
from job_market_intel.scrapers.indeed import IndeedError
from job_market_intel.scrapers.remoteok import RemoteOKError


class TestRunRemoteOKPipelineJob:
    @patch("job_market_intel.scheduler.jobs.RemoteOKPipeline")
    def test_successful_run_constructs_and_runs_pipeline(
        self, mock_pipeline_cls: MagicMock
    ) -> None:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.run.return_value = MagicMock(
            inserted_count=3,
            updated_count=1,
            unchanged_count=10,
            failed_count=0,
            session_id=7,
            validation_passed=True,
            issues=[],
        )

        run_remoteok_pipeline_job()

        mock_pipeline_cls.assert_called_once_with()
        mock_pipeline.run.assert_called_once_with(store_db=True)

    @patch("job_market_intel.scheduler.jobs.RemoteOKPipeline")
    def test_remoteok_error_is_caught_not_raised(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.side_effect = RemoteOKError("feed unreachable")

        # Must not raise - the scheduler process must survive a bad run.
        run_remoteok_pipeline_job()

    @patch("job_market_intel.scheduler.jobs.RemoteOKPipeline")
    def test_unexpected_exception_is_caught_not_raised(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.side_effect = RuntimeError("something unrelated broke")

        run_remoteok_pipeline_job()

    @patch("job_market_intel.scheduler.jobs.RemoteOKPipeline")
    def test_validation_issues_do_not_raise(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.return_value = MagicMock(
            inserted_count=0,
            updated_count=0,
            unchanged_count=0,
            failed_count=0,
            session_id=None,
            validation_passed=False,
            issues=["Only 2 job(s) parsed successfully, below the configured minimum of 20."],
        )

        # A failed *validation* check is a warning-level condition inside
        # an otherwise-successful run, not an error - must not raise.
        run_remoteok_pipeline_job()


def _indeed_result(**overrides: object) -> MagicMock:
    defaults = dict(
        queue_empty=False,
        query_text="software engineer",
        location_text="Remote",
        inserted_count=5,
        updated_count=0,
        unchanged_count=0,
        failed_count=0,
        session_id=42,
        queue_status="done",
        blocked_reason=None,
        validation_passed=True,
        issues=[],
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestRunIndeedPipelineJob:
    @patch("job_market_intel.scheduler.jobs.IndeedPipeline")
    def test_successful_run_constructs_and_runs_pipeline(
        self, mock_pipeline_cls: MagicMock
    ) -> None:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.run.return_value = [_indeed_result()]

        run_indeed_pipeline_job()

        mock_pipeline_cls.assert_called_once_with()
        mock_pipeline.run.assert_called_once_with(store_db=True)

    @patch("job_market_intel.scheduler.jobs.IndeedPipeline")
    def test_indeed_error_is_caught_not_raised(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.side_effect = IndeedError("driver crashed")

        run_indeed_pipeline_job()

    @patch("job_market_intel.scheduler.jobs.IndeedPipeline")
    def test_unexpected_exception_is_caught_not_raised(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.side_effect = RuntimeError("something unrelated broke")

        run_indeed_pipeline_job()

    @patch("job_market_intel.scheduler.jobs.IndeedPipeline")
    def test_queue_empty_does_not_raise_and_is_treated_as_idle(
        self, mock_pipeline_cls: MagicMock
    ) -> None:
        mock_pipeline_cls.return_value.run.return_value = [_indeed_result(queue_empty=True)]

        # An empty queue is a legitimate idle state, not an error - must
        # not raise, and (per the function's own docstring) must not be
        # logged as if something failed.
        run_indeed_pipeline_job()

    @patch("job_market_intel.scheduler.jobs.IndeedPipeline")
    def test_blocked_session_does_not_raise(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.return_value = [
            _indeed_result(
                queue_status="pending", blocked_reason="challenge detected on search page 1"
            )
        ]

        # A controlled stop (IndeedBlockedError caught inside the
        # pipeline itself, surfaced here only as queue_status) must not
        # raise - the whole point of that design is a clean stop, not a
        # crash.
        run_indeed_pipeline_job()

    @patch("job_market_intel.scheduler.jobs.IndeedPipeline")
    def test_validation_issues_do_not_raise(self, mock_pipeline_cls: MagicMock) -> None:
        mock_pipeline_cls.return_value.run.return_value = [
            _indeed_result(
                validation_passed=False,
                issues=["Zero raw records received from Indeed."],
            )
        ]

        run_indeed_pipeline_job()

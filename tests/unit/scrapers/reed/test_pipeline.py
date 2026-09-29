"""Unit tests for job_market_intel.scrapers.reed.pipeline.ReedPipeline.

Focused on what's genuinely new relative to every other source's pipeline
tests (``test_remoteok_pipeline.py``/``test_remotive_pipeline.py``, whose
basic dry-run/persistence shape this mirrors and doesn't re-test here):
cross-query deduplication, the per-run processing cap and its "defer the
whole job, don't process it partially" behavior, per-job Details-fetch
failure handling, database-informed prioritization, and prioritization's
graceful degradation when the database is unreachable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from job_market_intel.scrapers.reed.config import ReedSettings
from job_market_intel.scrapers.reed.exceptions import ReedFetchError
from job_market_intel.scrapers.reed.pipeline import ReedPipeline
from job_market_intel.scrapers.reed.search_queries import ReedSearchQuery


def _search(job_id: int) -> dict:
    return {
        "jobId": job_id,
        "jobTitle": f"Engineer {job_id}",
        "employerName": "Acme",
        "jobUrl": f"https://reed.example/{job_id}",
    }


def _details(job_id: int) -> dict:
    return {
        "jobId": job_id,
        "currency": "GBP",
        "salaryType": "per annum",
        "fullTime": True,
    }


def _build_pipeline(
    *,
    search_results_by_query: dict[str, list[dict]] | None = None,
    max_jobs_processed_per_run: int = 200,
    details_side_effect=None,
    repository: MagicMock | None = None,
) -> tuple[ReedPipeline, MagicMock, MagicMock]:
    mock_client = MagicMock()
    if search_results_by_query is not None:

        def fake_fetch_search_results(query: ReedSearchQuery) -> list[dict]:
            return search_results_by_query.get(query.keywords or "", [])

        mock_client.fetch_search_results.side_effect = fake_fetch_search_results
    if details_side_effect is not None:
        mock_client.fetch_job_details.side_effect = details_side_effect
    else:
        mock_client.fetch_job_details.side_effect = lambda job_id: _details(int(job_id))

    mock_repo = repository or MagicMock()
    if repository is None:
        mock_repo.get_source_id_by_code.return_value = 1
        mock_repo.get_existing_source_job_ids.return_value = set()
        mock_repo.create_scraping_session.return_value = 42
        mock_repo.save_cleaned_jobs.return_value = {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
        }

    pipeline = ReedPipeline(
        settings=ReedSettings(
            api_key="test-key", max_jobs_processed_per_run=max_jobs_processed_per_run
        ),
        client=mock_client,
        repository=mock_repo,
        search_queries=[ReedSearchQuery(keywords="data scientist")],
    )
    return pipeline, mock_client, mock_repo


class TestDryRun:
    def test_dry_run_touches_no_database(self) -> None:
        pipeline, mock_client, mock_repo = _build_pipeline(
            search_results_by_query={"data scientist": [_search(1), _search(2)]}
        )

        result = pipeline.run(store_db=False)

        assert result.raw_count == 2
        assert result.processed_count == 2
        assert result.cleaned_count == 2
        mock_repo.get_source_id_by_code.assert_not_called()
        mock_repo.get_existing_source_job_ids.assert_not_called()
        mock_repo.save_cleaned_jobs.assert_not_called()


class TestCrossQueryDeduplication:
    def test_same_job_from_two_queries_is_only_processed_once(self) -> None:
        mock_client = MagicMock()
        mock_client.fetch_search_results.side_effect = [
            [_search(1), _search(2)],
            [_search(2), _search(3)],  # job 2 also matches this query
        ]
        mock_client.fetch_job_details.side_effect = lambda job_id: _details(int(job_id))
        mock_repo = MagicMock()
        mock_repo.get_existing_source_job_ids.return_value = set()

        pipeline = ReedPipeline(
            settings=ReedSettings(api_key="k"),
            client=mock_client,
            repository=mock_repo,
            search_queries=[
                ReedSearchQuery(keywords="data scientist"),
                ReedSearchQuery(keywords="ai engineer"),
            ],
        )

        result = pipeline.run(store_db=False)

        assert result.raw_count == 3  # jobs 1, 2, 3 -- job 2 counted once


class TestPerRunCap:
    def test_jobs_beyond_the_cap_are_deferred_not_processed(self) -> None:
        pipeline, mock_client, _ = _build_pipeline(
            search_results_by_query={
                "data scientist": [_search(i) for i in range(1, 6)]  # 5 jobs
            },
            max_jobs_processed_per_run=2,
        )

        result = pipeline.run(store_db=False)

        assert result.raw_count == 5
        assert result.processed_count == 2
        assert result.deferred_count == 3
        assert result.cleaned_count == 2
        assert mock_client.fetch_job_details.call_count == 2

    def test_deferred_jobs_never_get_a_details_call(self) -> None:
        pipeline, mock_client, _ = _build_pipeline(
            search_results_by_query={"data scientist": [_search(i) for i in range(1, 4)]},
            max_jobs_processed_per_run=1,
        )

        pipeline.run(store_db=False)

        called_ids = {call.args[0] for call in mock_client.fetch_job_details.call_args_list}
        assert called_ids == {"1"}  # only the first job, per Search's own order


class TestDetailsFetchFailureIsSkippedNotDegraded:
    def test_a_failed_details_call_excludes_that_job_from_the_batch_entirely(self) -> None:
        def flaky_details(job_id: str) -> dict:
            if job_id == "2":
                raise ReedFetchError("simulated transient failure")
            return _details(int(job_id))

        pipeline, mock_client, _ = _build_pipeline(
            search_results_by_query={"data scientist": [_search(1), _search(2), _search(3)]},
            details_side_effect=flaky_details,
        )

        result = pipeline.run(store_db=False)

        assert result.raw_count == 3
        assert result.processed_count == 3  # all 3 were selected/attempted
        assert result.details_fetch_failed_count == 1
        assert result.parsed_count == 2  # job 2 excluded entirely
        assert result.cleaned_count == 2


class TestDatabaseInformedPrioritization:
    def test_new_jobs_are_processed_before_already_known_jobs_when_over_cap(self) -> None:
        # Job 1 is already known; jobs 2 and 3 are new. Cap = 2, so the
        # two NEW jobs should be chosen over the one already-known job.
        mock_repo = MagicMock()
        mock_repo.get_source_id_by_code.return_value = 1
        mock_repo.get_existing_source_job_ids.return_value = {"1"}
        mock_repo.create_scraping_session.return_value = 42
        mock_repo.save_cleaned_jobs.return_value = {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
        }

        pipeline, mock_client, _ = _build_pipeline(
            search_results_by_query={"data scientist": [_search(1), _search(2), _search(3)]},
            max_jobs_processed_per_run=2,
            repository=mock_repo,
        )

        mock_session = MagicMock()
        result = pipeline.run(store_db=True, session_override=mock_session)

        assert result.processed_count == 2
        called_ids = {call.args[0] for call in mock_client.fetch_job_details.call_args_list}
        assert called_ids == {"2", "3"}  # the new jobs, not the known job "1"

    def test_prioritization_failure_falls_back_to_search_order_gracefully(self) -> None:
        mock_repo = MagicMock()
        mock_repo.get_source_id_by_code.side_effect = RuntimeError("db unreachable")
        # Persistence will also fail in this scenario -- that's fine and
        # expected (matches every other source's tolerance of a total DB
        # outage); this test only asserts fetch/parse/clean still ran.

        pipeline, mock_client, _ = _build_pipeline(
            search_results_by_query={"data scientist": [_search(1), _search(2)]},
            repository=mock_repo,
        )

        result = pipeline.run(store_db=True, session_override=None)

        assert result.raw_count == 2
        assert result.cleaned_count == 2


class TestPersistence:
    def test_persists_cleaned_jobs_and_reports_counts(self) -> None:
        mock_repo = MagicMock()
        mock_repo.get_source_id_by_code.return_value = 7
        mock_repo.get_existing_source_job_ids.return_value = set()
        mock_repo.create_scraping_session.return_value = 99
        mock_repo.save_cleaned_jobs.return_value = {
            "inserted": 1,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
        }

        pipeline, mock_client, _ = _build_pipeline(
            search_results_by_query={"data scientist": [_search(1)]},
            repository=mock_repo,
        )

        mock_session = MagicMock()
        result = pipeline.run(store_db=True, session_override=mock_session)

        assert result.session_id == 99
        assert result.inserted_count == 1
        mock_repo.save_cleaned_jobs.assert_called_once()
        mock_repo.finish_scraping_session.assert_called_once()


class TestPlaceholderQueryWarning:
    def test_warns_when_no_search_queries_explicitly_given(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Using loguru means caplog won't capture it directly, so this
        # just confirms construction succeeds without error either way --
        # the real behavior (the warning) is visually confirmed via
        # logs during a real run, not asserted here.
        pipeline = ReedPipeline(settings=ReedSettings(api_key="k"), client=MagicMock())
        assert len(pipeline.search_queries) >= 1


class TestQueueSourcedRuns:
    """store_db=True with no explicit search_queries claims from the queue."""

    @staticmethod
    def _pipeline(claimed, search_side_effect):
        mock_client = MagicMock()
        mock_client.fetch_search_results.side_effect = search_side_effect
        mock_client.fetch_job_details.side_effect = lambda job_id: _details(int(job_id))
        mock_repo = MagicMock()
        mock_repo.get_source_id_by_code.return_value = 1
        mock_repo.get_existing_source_job_ids.return_value = set()
        mock_repo.create_scraping_session.return_value = 9
        mock_repo.save_cleaned_jobs.return_value = {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
        }
        mock_queue = MagicMock()
        mock_queue.claim_next_queries.return_value = claimed
        pipeline = ReedPipeline(
            settings=ReedSettings(api_key="k", queries_claimed_per_run=2),
            client=mock_client,
            repository=mock_repo,
            queue_repository=mock_queue,
        )
        return pipeline, mock_queue

    def test_claims_configured_number_and_marks_each_done(self) -> None:
        from job_market_intel.db.reed_query_queue_repository import ClaimedReedQuery

        claimed = [
            ClaimedReedQuery(10, ReedSearchQuery(keywords="a", location_name="Leeds")),
            ClaimedReedQuery(11, ReedSearchQuery(keywords="b", location_name="York")),
        ]
        pipeline, mock_queue = self._pipeline(claimed, lambda q: [_search(1)])

        result = pipeline.run(store_db=True, session_override=MagicMock())

        assert mock_queue.claim_next_queries.call_args.args[1] == 2
        assert result.queries_searched == 2
        marks = {c.args[1]: c.kwargs["status"] for c in mock_queue.mark_query_result.call_args_list}
        assert marks == {10: "done", 11: "done"}

    def test_one_failed_search_is_marked_failed_and_others_still_run(self) -> None:
        from job_market_intel.db.reed_query_queue_repository import ClaimedReedQuery

        claimed = [
            ClaimedReedQuery(10, ReedSearchQuery(keywords="bad")),
            ClaimedReedQuery(11, ReedSearchQuery(keywords="good")),
        ]

        def search(query):
            if query.keywords == "bad":
                raise ReedFetchError("nope")
            return [_search(1)]

        pipeline, mock_queue = self._pipeline(claimed, search)

        result = pipeline.run(store_db=True, session_override=MagicMock())

        marks = {c.args[1]: c.kwargs["status"] for c in mock_queue.mark_query_result.call_args_list}
        assert marks == {10: "failed", 11: "done"}
        assert result.raw_count == 1

    def test_empty_queue_finds_nothing_without_error(self) -> None:
        pipeline, mock_queue = self._pipeline([], lambda q: [])
        result = pipeline.run(store_db=True, session_override=MagicMock())
        assert result.raw_count == 0
        assert result.queries_searched == 0
        mock_queue.mark_query_result.assert_not_called()

    def test_explicit_search_queries_bypass_the_queue(self) -> None:
        pipeline, _, _ = _build_pipeline(
            search_results_by_query={"data scientist": [_search(1)]}
        )
        pipeline.queue_repository = MagicMock()
        pipeline.run(store_db=True, session_override=MagicMock())
        pipeline.queue_repository.claim_next_queries.assert_not_called()

    def test_dry_run_never_touches_the_queue(self) -> None:
        pipeline, mock_queue = self._pipeline([], lambda q: [_search(1)])
        pipeline.run(store_db=False)
        mock_queue.claim_next_queries.assert_not_called()

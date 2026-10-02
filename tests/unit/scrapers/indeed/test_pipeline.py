"""Unit tests for job_market_intel.scrapers.indeed.pipeline.IndeedPipeline.

Every collaborator (browser client, cleaner, validator, both repositories,
and db.session.get_session) is injected or patched — this suite is about
IndeedPipeline's own control flow (claim -> browse -> validate -> clean ->
persist -> record), not about Selenium, BeautifulSoup, or a real database.
Those are covered separately by test_client.py, test_parser.py,
test_indeed_cleaner.py, test_indeed_validator.py, and (for the real
database path) a live integration test this delivery does not yet include
— see the accompanying chat message's known-gaps list.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from job_market_intel.db.scrape_queue_repository import ClaimedQuery
from job_market_intel.scrapers.indeed.exceptions import IndeedFetchError
from job_market_intel.scrapers.indeed.models import RawIndeedJob
from job_market_intel.scrapers.indeed.pipeline import IndeedPipeline
from job_market_intel.validation.common import BatchValidationReport


def _raw_job(source_job_id: str = "abc123") -> RawIndeedJob:
    return RawIndeedJob.model_validate(
        {
            "source_job_id": source_job_id,
            "job_title": "Software Engineer",
            "company_name": "Acme Corp",
            "query_text": "software engineer",
            "location_text": "Remote",
            "search_page_number": 1,
            "detail_url": f"https://www.indeed.com/viewjob?jk={source_job_id}",
        }
    )


@contextmanager
def _fake_get_session():
    yield MagicMock()


def _build_pipeline(
    *,
    claimed: ClaimedQuery | None,
    client: MagicMock,
    repository: MagicMock | None = None,
    queue_repository: MagicMock | None = None,
) -> tuple[IndeedPipeline, MagicMock, MagicMock]:
    client.open_detail_in_new_tab.return_value = (
        '<html><body><div class="react-native-html-content '
        'simple-job-description-html">Details.</div></body></html>'
    )
    repository = repository or MagicMock()
    repository.get_source_id_by_code.return_value = 42
    repository.save_cleaned_jobs.return_value = {
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
    }
    repository.create_scraping_session.return_value = 999

    queue_repository = queue_repository or MagicMock()
    queue_repository.claim_next_queries.return_value = [claimed] if claimed is not None else []

    validator = MagicMock()
    validator.validate.return_value = BatchValidationReport(
        passed=True,
        total_raw_records=1,
        total_parsed=1,
        total_skipped=0,
        skip_rate=0.0,
        duplicate_source_job_ids=[],
        missing_field_rates={},
        issues=[],
    )

    cleaner = MagicMock()
    cleaner.clean_jobs.side_effect = lambda jobs: list(jobs)  # pass through unchanged

    pipeline = IndeedPipeline(
        client=client,
        repository=repository,
        queue_repository=queue_repository,
        validator=validator,
        cleaner=cleaner,
    )
    return pipeline, repository, queue_repository


class TestQueueEmpty:
    def test_returns_early_with_queue_empty_flag(self) -> None:
        client = MagicMock()
        pipeline, repository, queue_repository = _build_pipeline(claimed=None, client=client)

        with patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session):
            results = pipeline.run(store_db=True)

        assert results[0].queue_empty is True
        client.open_session.assert_not_called()
        repository.save_cleaned_jobs.assert_not_called()


class TestHappyPath:
    def test_single_page_no_next_link_marks_done_and_persists(self) -> None:
        claimed = ClaimedQuery(
            query_id=1, query_text="engineer", location_text="Remote", last_page_reached=0
        )
        client = MagicMock()
        client.open_session.return_value = None
        client.open_search.return_value = "<html>page one</html>"
        client.go_to_next_search_page.return_value = None  # no further pages
        client.detect_challenge.return_value = False
        client.search_pages_visited = 1
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed, client=client)

        with (
            patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session),
            patch(
                "job_market_intel.scrapers.indeed.pipeline.parse_search_page",
                return_value=[_raw_job()],
            ),
        ):
            results = pipeline.run(store_db=True)

        assert results[0].queue_empty is False
        assert results[0].queue_status == "done"
        assert results[0].raw_count == 1
        assert results[0].cleaned_count == 1
        assert results[0].inserted_count == 1
        client.close_session.assert_called_once()
        queue_repository.mark_query_result.assert_called_once()
        _, kwargs = queue_repository.mark_query_result.call_args
        assert kwargs["status"] == "done"
        assert kwargs["error"] is None

    def test_session_page_cap_reached_marks_pending(self) -> None:
        claimed = ClaimedQuery(
            query_id=2, query_text="engineer", location_text="Remote", last_page_reached=0
        )
        client = MagicMock()
        client.open_search.return_value = "<html>page one</html>"
        client.detect_challenge.return_value = False
        # search_pages_visited is read live by the pipeline after each
        # page; simulate the cap being hit immediately after page 1.
        client.search_pages_visited = 5  # equals IndeedSettings default max
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed, client=client)

        with (
            patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session),
            patch(
                "job_market_intel.scrapers.indeed.pipeline.parse_search_page",
                return_value=[_raw_job()],
            ),
        ):
            results = pipeline.run(store_db=True)

        assert results[0].queue_status == "pending"
        client.go_to_next_search_page.assert_not_called()

    def test_dry_run_skips_persistence_but_still_scrapes_and_cleans(self) -> None:
        claimed = ClaimedQuery(
            query_id=3, query_text="engineer", location_text="Remote", last_page_reached=0
        )
        client = MagicMock()
        client.open_search.return_value = "<html>page one</html>"
        client.go_to_next_search_page.return_value = None
        client.detect_challenge.return_value = False
        client.search_pages_visited = 1
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed, client=client)

        with (
            patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session),
            patch(
                "job_market_intel.scrapers.indeed.pipeline.parse_search_page",
                return_value=[_raw_job()],
            ),
        ):
            results = pipeline.run(store_db=False)

        assert results[0].cleaned_count == 1
        assert results[0].session_id is None
        repository.save_cleaned_jobs.assert_not_called()
        queue_repository.mark_query_result.assert_not_called()


class TestBlockedSession:
    def test_challenge_on_first_page_marks_failed_with_reason(self) -> None:
        claimed = ClaimedQuery(
            query_id=4, query_text="engineer", location_text="Remote", last_page_reached=0
        )
        client = MagicMock()
        client.open_search.return_value = "<html>Please verify you are a human</html>"
        client.detect_challenge.return_value = True
        client.search_pages_visited = 1
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed, client=client)

        with patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session):
            results = pipeline.run(store_db=True)

        assert results[0].queue_status == "failed"
        assert results[0].blocked_reason is not None
        assert "challenge detected" in results[0].blocked_reason
        client.close_session.assert_called_once()
        _, kwargs = queue_repository.mark_query_result.call_args
        assert kwargs["status"] == "failed"
        assert kwargs["error"] == results[0].blocked_reason

    def test_consecutive_fetch_failures_trigger_blocked(self) -> None:
        claimed = ClaimedQuery(
            query_id=5, query_text="engineer", location_text="Remote", last_page_reached=0
        )
        client = MagicMock()
        client.open_search.return_value = "<html>page one</html>"
        client.detect_challenge.return_value = False
        client.go_to_next_search_page.side_effect = IndeedFetchError("boom")
        client.search_pages_visited = 1
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed, client=client)
        pipeline.settings.max_consecutive_failures = 2
        pipeline.settings.max_search_pages_per_session = 10

        with (
            patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session),
            patch(
                "job_market_intel.scrapers.indeed.pipeline.parse_search_page",
                return_value=[],
            ),
        ):
            results = pipeline.run(store_db=True)

        assert results[0].queue_status == "failed"
        assert "consecutive fetch failures" in results[0].blocked_reason

    def test_close_session_always_called_even_when_blocked(self) -> None:
        claimed = ClaimedQuery(
            query_id=6, query_text="engineer", location_text="Remote", last_page_reached=0
        )
        client = MagicMock()
        client.open_search.side_effect = IndeedFetchError("driver crashed")
        client.search_pages_visited = 0
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed, client=client)
        pipeline.settings.max_consecutive_failures = 1

        with patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session):
            pipeline.run(store_db=True)

        client.close_session.assert_called_once()


class TestMultiItemRun:
    def test_claims_up_to_items_per_run_and_works_each(self) -> None:
        claimed = [
            ClaimedQuery(
                query_id=10, query_text="engineer", location_text="Remote", last_page_reached=0
            ),
            ClaimedQuery(
                query_id=11, query_text="analyst", location_text="Berlin", last_page_reached=0
            ),
        ]
        client = MagicMock()
        client.open_search.return_value = "<html>page one</html>"
        client.go_to_next_search_page.return_value = None
        client.detect_challenge.return_value = False
        client.search_pages_visited = 1
        client.detail_pages_visited = 0

        pipeline, repository, queue_repository = _build_pipeline(claimed=claimed[0], client=client)
        queue_repository.claim_next_queries.return_value = claimed

        with (
            patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session),
            patch(
                "job_market_intel.scrapers.indeed.pipeline.parse_search_page",
                return_value=[_raw_job()],
            ),
        ):
            results = pipeline.run(store_db=True)

        assert len(results) == 2
        assert results[0].query_text == "engineer"
        assert results[1].query_text == "analyst"
        assert repository.save_cleaned_jobs.call_count == 2
        assert queue_repository.mark_query_result.call_count == 2

    def test_blocked_first_item_releases_unworked_rows_back_to_pending(self) -> None:
        claimed = [
            ClaimedQuery(
                query_id=20, query_text="engineer", location_text="Remote", last_page_reached=0
            ),
            ClaimedQuery(
                query_id=21, query_text="analyst", location_text="Berlin", last_page_reached=0
            ),
        ]
        client = MagicMock()
        client.open_search.return_value = "<html>Please verify you are a human</html>"
        client.detect_challenge.return_value = True
        client.search_pages_visited = 1
        client.detail_pages_visited = 0

        pipeline, _repository, queue_repository = _build_pipeline(claimed=claimed[0], client=client)
        queue_repository.claim_next_queries.return_value = claimed

        with patch("job_market_intel.scrapers.indeed.pipeline.get_session", _fake_get_session):
            results = pipeline.run(store_db=True)

        assert len(results) == 1
        assert results[0].queue_status == "failed"
        queue_repository.release_claimed_queries.assert_called_once()
        released_ids = queue_repository.release_claimed_queries.call_args[0][1]
        assert released_ids == [21]


class TestFillInDescriptionsDoesNotRevisit:
    def test_a_job_whose_description_comes_back_none_is_not_revisited(self) -> None:
        # Regression test for a real bug caught on the first live run:
        # description_raw staying None (parse_detail_page found nothing)
        # used to mean the job looked "not yet attempted" forever, so a
        # second call to _fill_in_descriptions (as happens once per search
        # page within one session) would visit it again. Confirmed on a
        # real 2-page run: 16 jobs produced 21 detail-page visits.
        client = MagicMock()
        client.open_detail_in_new_tab.return_value = "<html>no description here</html>"
        client.detect_challenge.return_value = False
        client.detail_pages_visited = 0

        pipeline, _repository, _queue_repository = _build_pipeline(claimed=None, client=client)
        raw_jobs = [_raw_job("abc123")]
        attempted: set[str] = set()

        pipeline._fill_in_descriptions(raw_jobs, attempted)  # noqa: SLF001
        pipeline._fill_in_descriptions(raw_jobs, attempted)  # noqa: SLF001 - simulate page 2

        assert client.open_detail_in_new_tab.call_count == 1
        assert "abc123" in attempted

    def test_a_job_whose_description_is_found_is_also_not_revisited(self) -> None:
        client = MagicMock()
        client.open_detail_in_new_tab.return_value = (
            '<html><div class="react-native-html-content '
            'simple-job-description-html">Real description.</div></html>'
        )
        client.detect_challenge.return_value = False
        client.detail_pages_visited = 0

        pipeline, _repository, _queue_repository = _build_pipeline(claimed=None, client=client)
        raw_jobs = [_raw_job("abc123")]
        attempted: set[str] = set()

        pipeline._fill_in_descriptions(raw_jobs, attempted)  # noqa: SLF001
        pipeline._fill_in_descriptions(raw_jobs, attempted)  # noqa: SLF001

        assert client.open_detail_in_new_tab.call_count == 1
        assert raw_jobs[0].description_raw is not None

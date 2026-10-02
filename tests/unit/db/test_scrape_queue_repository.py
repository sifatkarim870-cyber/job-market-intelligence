"""Unit tests for job_market_intel.db.scrape_queue_repository.

Previously only exercised indirectly through scrapers/indeed/pipeline.py's
mocked tests — this repository never had its own test file until
claim_next_queries (the multi-row claim added for IndeedSettings.
items_per_run) made that worth fixing.

Uses a MagicMock session with a controllable .execute() so these tests
verify the repository's own SQL-shape and Python-level logic (limit
passed through, row mapping, status validation) without needing a real
database — the same style test_geographic_resolution.py already uses
for this kind of thing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from job_market_intel.db.exceptions import RepositoryError
from job_market_intel.db.scrape_queue_repository import ClaimedQuery, ScrapeQueueRepository


def _row(query_id: int, query_text: str, location_text: str, last_page_reached: int = 0):
    return SimpleNamespace(
        query_id=query_id,
        query_text=query_text,
        location_text=location_text,
        last_page_reached=last_page_reached,
    )


class TestClaimNextQueries:
    def test_returns_claimed_queries_mapped_from_rows(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = [
            _row(1, "software engineer", "Remote"),
            _row(2, "data analyst", "Germany"),
        ]
        repo = ScrapeQueueRepository()

        claimed = repo.claim_next_queries(session, source_id=4, limit=5)

        assert claimed == [
            ClaimedQuery(
                query_id=1, query_text="software engineer", location_text="Remote",
                last_page_reached=0,
            ),
            ClaimedQuery(
                query_id=2, query_text="data analyst", location_text="Germany",
                last_page_reached=0,
            ),
        ]

    def test_limit_is_passed_through_as_a_bound_parameter(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = []
        repo = ScrapeQueueRepository()

        repo.claim_next_queries(session, source_id=4, limit=7)

        _, params = session.execute.call_args[0]
        assert params["limit"] == 7
        assert params["source_id"] == 4

    def test_empty_result_returns_empty_list_not_none(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = []
        repo = ScrapeQueueRepository()

        claimed = repo.claim_next_queries(session, source_id=4, limit=10)

        assert claimed == []

    def test_fewer_eligible_rows_than_limit_is_not_an_error(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = [_row(1, "q", "l")]
        repo = ScrapeQueueRepository()

        claimed = repo.claim_next_queries(session, source_id=4, limit=10)

        assert len(claimed) == 1


class TestMarkQueryResultStillWorks:
    # Regression coverage: claim_next_queries is additive — confirm the
    # existing single-item method's own validation wasn't disturbed.
    def test_invalid_status_raises_repository_error(self) -> None:
        session = MagicMock()
        repo = ScrapeQueueRepository()

        with pytest.raises(RepositoryError):
            repo.mark_query_result(session, 1, status="bogus", last_page_reached=0)

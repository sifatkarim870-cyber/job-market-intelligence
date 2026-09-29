"""Unit tests for job_market_intel.db.reed_query_queue_repository.

SQL is exercised against a mocked Session (same approach as
test_job_repository.py): these check what gets sent and how results are
translated, not PostgreSQL's own behavior. The real claim/lock semantics
need the migration applied and are covered by a live check, not here.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from job_market_intel.db.exceptions import RepositoryError
from job_market_intel.db.reed_query_queue_repository import ReedQueryQueueRepository
from job_market_intel.scrapers.reed.search_queries import ReedSearchQuery


class TestSeedQuery:
    def test_none_becomes_empty_string_for_storage(self) -> None:
        session = MagicMock()
        ReedQueryQueueRepository().seed_query(session, ReedSearchQuery(keywords="x"))
        params = session.execute.call_args.args[1]
        assert params == {
            "keywords": "x",
            "location_name": "",
            "distance_from_location": None,
        }

    def test_uses_on_conflict_do_nothing(self) -> None:
        session = MagicMock()
        ReedQueryQueueRepository().seed_query(
            session, ReedSearchQuery(keywords="x", location_name="London")
        )
        sql = str(session.execute.call_args.args[0])
        assert "ON CONFLICT (keywords, location_name) DO NOTHING" in sql


class TestClaimNextQueries:
    def test_empty_strings_become_none_on_the_returned_query(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = [
            SimpleNamespace(
                query_id=1, keywords="", location_name="Leeds", distance_from_location=5
            )
        ]
        claimed = ReedQueryQueueRepository().claim_next_queries(session, 3)
        assert len(claimed) == 1
        assert claimed[0].query_id == 1
        assert claimed[0].search_query == ReedSearchQuery(
            keywords=None, location_name="Leeds", distance_from_location=5
        )

    def test_no_eligible_rows_returns_empty_list(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = []
        assert ReedQueryQueueRepository().claim_next_queries(session, 5) == []

    def test_passes_limit_and_locks_with_skip_locked(self) -> None:
        session = MagicMock()
        session.execute.return_value.all.return_value = []
        ReedQueryQueueRepository().claim_next_queries(session, 4)
        assert session.execute.call_args.args[1] == {"limit": 4}
        assert "FOR UPDATE SKIP LOCKED" in str(session.execute.call_args.args[0])


class TestMarkQueryResult:
    @pytest.mark.parametrize("status", ["done", "failed"])
    def test_valid_statuses_are_written(self, status: str) -> None:
        session = MagicMock()
        ReedQueryQueueRepository().mark_query_result(session, 7, status=status, error="boom")
        assert session.execute.call_args.args[1] == {
            "status": status,
            "error": "boom",
            "query_id": 7,
        }

    @pytest.mark.parametrize("status", ["pending", "in_progress", "nonsense"])
    def test_invalid_status_raises_without_touching_the_database(self, status: str) -> None:
        session = MagicMock()
        with pytest.raises(RepositoryError):
            ReedQueryQueueRepository().mark_query_result(session, 7, status=status)
        session.execute.assert_not_called()


class TestAddAndUpdateAreDeliberatelyUnsupported:
    def test_add_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            ReedQueryQueueRepository().add(MagicMock(), object())

    def test_update_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            ReedQueryQueueRepository().update(MagicMock(), object())

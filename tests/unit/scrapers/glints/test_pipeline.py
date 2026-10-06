"""Unit tests for the Glints pipeline's skip-known wiring.

Covers the three decisions ``pipeline.run`` makes around discovery:

1. ``store_db=False`` never queries the database (dry runs must not
   need one) and passes no exclusion — newest window, like a fresh
   scrape.
2. ``store_db=True`` loads the source's known uuids and hands them to
   the client, so a capped run fetches only unseen jobs.
3. A failed known-ids lookup degrades to "no exclusion" (old fetch
   behavior) instead of suppressing the scrape — persistence still
   surfaces the database problem.

Persistence itself is monkeypatched: these are unit tests; the real
save path is covered by the live-DB runs recorded in the scraper's
commit history.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import job_market_intel.scrapers.glints.pipeline as pipeline_module
from job_market_intel.scrapers.glints.pipeline import GlintsPipeline

KNOWN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@contextmanager
def _fake_session() -> Any:
    """Stand-in for ``db.session.get_session``: no connection, ever."""
    yield object()


class FakeClient:
    """Records how the pipeline called ``fetch_raw_jobs``."""

    def __init__(self, records: list[dict] | None = None) -> None:
        self.records = records if records is not None else []
        self.exclude_args: list[set[str] | None] = []

    def fetch_raw_jobs(self, *, exclude_ids: set[str] | None = None) -> list[dict]:
        self.exclude_args.append(exclude_ids)
        return list(self.records)


class FakeRepository:
    def __init__(self, ids: set[str] | None = None, *, fail: bool = False) -> None:
        self.ids = ids if ids is not None else set()
        self.fail = fail

    def get_source_id_by_code(self, session: Any, code: str) -> int:
        assert code == "glints"
        return 93

    def get_all_source_job_ids(self, session: Any, source_id: int) -> set[str]:
        if self.fail:
            raise RuntimeError("connection refused")
        return self.ids


@pytest.fixture(autouse=True)
def persisted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture ``_persist_with_session`` calls so no database is touched.

    Also swaps ``get_session`` for a connectionless stand-in: every
    ``store_db=True`` path opens one (either for the known-ids lookup
    or for persistence), and unit tests must never open a real one.
    """
    calls: list[dict[str, Any]] = []

    def fake_persist(self: Any, session: Any, cleaned_jobs: list[Any], raw_count: int, result: Any) -> None:
        calls.append({"cleaned_jobs": cleaned_jobs, "raw_count": raw_count, "result": result})

    monkeypatch.setattr(GlintsPipeline, "_persist_with_session", fake_persist)
    monkeypatch.setattr(pipeline_module, "get_session", _fake_session)
    return calls


def _pipeline(client: FakeClient, repository: FakeRepository | None = None) -> GlintsPipeline:
    return GlintsPipeline(
        client=client,
        repository=repository if repository is not None else FakeRepository(),
    )


class TestSkipKnownWiring:
    def test_dry_run_never_queries_known_ids(self, persisted: list[dict[str, Any]]) -> None:
        client = FakeClient()
        pipeline = _pipeline(client)

        result = pipeline.run(store_db=False)

        assert client.exclude_args == [None]
        assert result.raw_count == 0
        assert result.session_id is None
        assert persisted == []  # store_db=False: nothing persisted

    def test_db_run_passes_known_ids_as_exclusion(
        self, persisted: list[dict[str, Any]]
    ) -> None:
        client = FakeClient()
        pipeline = _pipeline(client, FakeRepository(ids={KNOWN_ID}))

        pipeline.run(store_db=True)

        assert client.exclude_args == [{KNOWN_ID}]
        assert len(persisted) == 1  # zero-job run still records a session

    def test_known_ids_lookup_failure_degrades_to_no_exclusion(
        self,
        persisted: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # First get_session() (known-ids lookup) fails; the persistence
        # one afterwards must still work — the scrape degrades, it
        # does not die.
        state = {"calls": 0}

        @contextmanager
        def boom_first() -> Any:
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("database down")
            yield object()

        monkeypatch.setattr(pipeline_module, "get_session", boom_first)
        client = FakeClient()
        pipeline = _pipeline(client, FakeRepository(fail=True))

        pipeline.run(store_db=True)

        # Degraded, not dead: fetch proceeds like a fresh scrape...
        assert client.exclude_args == [None]
        # ...and persistence still runs afterwards.
        assert len(persisted) == 1


class TestKnownIdsLoading:
    def test_uses_override_session_without_opening_a_new_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = _pipeline(FakeClient(), FakeRepository(ids={KNOWN_ID}))

        def explode() -> Any:
            raise AssertionError("get_session must not be called with an override")

        monkeypatch.setattr(pipeline_module, "get_session", explode)

        assert pipeline._load_known_ids(object()) == {KNOWN_ID}

    def test_repository_failure_returns_none(self) -> None:
        pipeline = _pipeline(FakeClient(), FakeRepository(fail=True))

        assert pipeline._load_known_ids(None) is None

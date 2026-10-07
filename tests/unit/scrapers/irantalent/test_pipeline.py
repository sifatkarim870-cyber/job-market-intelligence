"""Unit tests for the Irantalent pipeline's batch flow.

Mirrors ``tests/unit/scrapers/jobvision/test_pipeline.py`` with the
skip-known wiring REMOVED — IranTalent's search endpoint is a
newest-first cursor, so the pipeline hands the client no exclusion
(content-hash dedup absorbs overlap) and never loads known ids:

1. ``store_db=False`` never touches the database.
2. ``store_db=True`` records an honest session even for an empty batch.
3. Records flow parse -> validate -> clean -> persist.
4. A fetch failure propagates (the client raises loudly by contract).
5. ``session_override`` bypasses ``get_session`` entirely.

Persistence itself is monkeypatched: these are unit tests; the real
save path is covered by the CI runs.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import job_market_intel.scrapers.irantalent.pipeline as pipeline_module
from job_market_intel.scrapers.irantalent.pipeline import IrantalentPipeline
from job_market_intel.validation.irantalent_validator import IrantalentValidationSettings

URL = "https://www.irantalent.com/fa/job/accountant/42"


@contextmanager
def _fake_session() -> Any:
    """Stand-in for ``db.session.get_session``: no connection, ever."""
    yield object()


class FakeClient:
    """Records how often the pipeline called ``fetch_raw_jobs``."""

    def __init__(self, records: list[dict] | None = None) -> None:
        self.records = records if records is not None else []
        self.calls = 0

    def fetch_raw_jobs(self) -> list[dict]:
        self.calls += 1
        return list(self.records)


class FakeRepository:
    def get_source_id_by_code(self, session: Any, code: str) -> int:
        assert code == "irantalent"
        return 95

    def create_scraping_session(self, session: Any, *, source_id: int, trigger_type: str) -> int:
        return 11


@pytest.fixture(autouse=True)
def persisted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture ``_persist_with_session`` calls so no database is touched.

    Also swaps ``get_session`` for a connectionless stand-in: every
    ``store_db=True`` path opens one, and unit tests must never open a
    real one.
    """
    calls: list[dict[str, Any]] = []

    def fake_persist(
        self: Any, session: Any, cleaned_jobs: list[Any], raw_count: int, result: Any
    ) -> None:
        # Like the real one, it claims a session id for the run.
        result.session_id = 7
        calls.append({"cleaned_jobs": cleaned_jobs, "raw_count": raw_count, "result": result})

    monkeypatch.setattr(IrantalentPipeline, "_persist_with_session", fake_persist)
    monkeypatch.setattr(pipeline_module, "get_session", _fake_session)
    return calls


def _pipeline(
    client: FakeClient,
    *,
    min_expected_jobs: int = 100,
) -> IrantalentPipeline:
    return IrantalentPipeline(
        client=client,
        repository=FakeRepository(),
        validation_settings=IrantalentValidationSettings(min_expected_jobs=min_expected_jobs),
    )


class TestStoreDbFlag:
    def test_dry_run_never_queries_the_database(self, persisted: list[dict[str, Any]]) -> None:
        client = FakeClient()
        pipeline = _pipeline(client)

        result = pipeline.run(store_db=False)

        assert client.calls == 1  # fetch still happens...
        assert result.raw_count == 0
        assert result.session_id is None
        assert persisted == []  # ...but nothing is persisted

    def test_db_run_records_a_session_even_for_an_empty_batch(
        self, persisted: list[dict[str, Any]]
    ) -> None:
        # The client raises on an empty cursor by contract; an empty
        # batch reaching persistence (stubbed client) still logs an
        # honest zero-jobs session rather than vanishing.
        pipeline = _pipeline(FakeClient())

        pipeline.run(store_db=True)

        assert len(persisted) == 1
        assert persisted[0]["raw_count"] == 0


class TestBatchFlow:
    def test_records_are_parsed_cleaned_and_persisted(
        self, persisted: list[dict[str, Any]]
    ) -> None:
        record = {"url": URL, "payload": {"id": 42, "title": "کارمند"}}
        pipeline = _pipeline(FakeClient(records=[record]), min_expected_jobs=1)

        result = pipeline.run(store_db=True)

        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.cleaned_count == 1
        assert result.validation_passed is True
        assert result.session_id is not None
        assert len(persisted) == 1
        assert len(persisted[0]["cleaned_jobs"]) == 1

    def test_fetch_failure_propagates(self, persisted: list[dict[str, Any]]) -> None:
        class BoomClient(FakeClient):
            def fetch_raw_jobs(self) -> list[dict]:
                raise RuntimeError("search unreachable")

        pipeline = _pipeline(BoomClient())

        with pytest.raises(RuntimeError):
            pipeline.run(store_db=True)
        assert persisted == []


class TestSessionOverride:
    def test_override_bypasses_get_session(
        self, persisted: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = _pipeline(FakeClient())

        def explode() -> Any:
            raise AssertionError("get_session must not be called with an override")

        monkeypatch.setattr(pipeline_module, "get_session", explode)

        result = pipeline.run(store_db=True, session_override=object())

        assert result.session_id is not None
        assert len(persisted) == 1

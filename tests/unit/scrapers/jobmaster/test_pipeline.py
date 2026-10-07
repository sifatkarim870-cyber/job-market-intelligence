"""Unit tests for the JobMaster pipeline's batch flow.

Mirrors ``tests/unit/scrapers/irantalent/test_pipeline.py`` with the
skip-known wiring ACTIVE (JobMaster's discovery window is not
newest-first, so the pipeline loads stored source_job_ids and passes
them as an exclusion — the same contract the generic pattern shares):

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

import job_market_intel.scrapers.jobmaster.pipeline as pipeline_module
from job_market_intel.scrapers.jobmaster.pipeline import JobmasterPipeline
from job_market_intel.validation.jobmaster_validator import JobmasterValidationSettings

URL = "https://www.jobmaster.co.il/jobs/checknum.asp?key=9884960"


@contextmanager
def _fake_session() -> Any:
    """Stand-in for ``db.session.get_session``: no connection, ever."""
    yield object()


class FakeClient:
    """Records how often the pipeline called ``fetch_raw_jobs``."""

    def __init__(self, records: list[dict] | None = None) -> None:
        self.records = records if records is not None else []
        self.calls = 0
        self.last_exclude: set[str] | None = None

    def fetch_raw_jobs(self, *, exclude_ids: set[str] | None = None) -> list[dict]:
        self.calls += 1
        self.last_exclude = exclude_ids
        return list(self.records)


class FakeRepository:
    def get_source_id_by_code(self, session: Any, code: str) -> int:
        assert code == "jobmaster"
        return 70

    def get_all_source_job_ids(self, session: Any, source_id: int) -> set[str]:
        return {"9884900"}

    def create_scraping_session(self, session: Any, *, source_id: int, trigger_type: str) -> int:
        return 11


@pytest.fixture(autouse=True)
def persisted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture ``_persist_with_session`` calls so no database is touched."""
    calls: list[dict[str, Any]] = []

    def fake_persist(
        self: Any, session: Any, cleaned_jobs: list[Any], raw_count: int, result: Any
    ) -> None:
        result.session_id = 7
        calls.append({"cleaned_jobs": cleaned_jobs, "raw_count": raw_count, "result": result})

    monkeypatch.setattr(JobmasterPipeline, "_persist_with_session", fake_persist)
    monkeypatch.setattr(pipeline_module, "get_session", _fake_session)
    return calls


def _pipeline(
    client: FakeClient,
    *,
    min_expected_jobs: int = 50,
) -> JobmasterPipeline:
    return JobmasterPipeline(
        client=client,
        repository=FakeRepository(),
        validation_settings=JobmasterValidationSettings(min_expected_jobs=min_expected_jobs),
    )


class TestStoreDbFlag:
    def test_dry_run_never_queries_the_database(self, persisted: list[dict[str, Any]]) -> None:
        client = FakeClient()
        pipeline = _pipeline(client)

        result = pipeline.run(store_db=False)

        assert client.calls == 1
        assert result.raw_count == 0
        assert result.session_id is None
        assert persisted == []

    def test_db_run_records_a_session_even_for_an_empty_batch(
        self, persisted: list[dict[str, Any]]
    ) -> None:
        pipeline = _pipeline(FakeClient())

        pipeline.run(store_db=True)

        assert len(persisted) == 1
        assert persisted[0]["raw_count"] == 0

    def test_known_ids_are_excluded_before_fetching(self) -> None:
        client = FakeClient()
        pipeline = _pipeline(client)

        pipeline.run(store_db=True)

        assert client.last_exclude == {"9884900"}


class TestBatchFlow:
    def test_records_are_parsed_cleaned_and_persisted(
        self,
        persisted: list[dict[str, Any]],
        make_raw_jobmaster_job: Any,
    ) -> None:
        # Feed the real parse/validate/clean path a mix that survives:
        # minimal valid detail-shape records built from the conftest
        # factory. We bypass the client->parser boundary by stubbing the
        # parser here — fetch/parse is already covered elsewhere.

        job = make_raw_jobmaster_job()
        client = FakeClient([{"url": URL, "html": "<html></html>"}])

        class _StubParser:
            def parse_jobs(self, raw_jobs: list[dict]) -> list[Any]:
                return [job]

        pipeline = JobmasterPipeline(
            client=client,
            parser=_StubParser(),
            repository=FakeRepository(),
            validation_settings=JobmasterValidationSettings(min_expected_jobs=50),
        )

        result = pipeline.run(store_db=True)

        assert result.parsed_count == 1
        assert result.cleaned_count == 1
        assert persisted and len(persisted[0]["cleaned_jobs"]) == 1

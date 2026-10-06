"""Unit tests for the Jobinja pipeline's run wiring.

Covers the decisions ``pipeline.run`` makes (and, just as importantly,
the ones it no longer makes — there is no skip-known exclusion here):

1. ``store_db=False`` never touches the database (dry runs must not
   need one) and returns counts without persistence.
2. ``store_db=True`` persists under source code ``jobinja`` and records
   the session, even when batch validation fails — validation issues
   are reported in the result, not used as a gate (the stance every
   other source takes).
3. A client failure (``JobinjaError`` family) propagates: discovery or
   total fetch failure means no run, visibly.

Persistence itself is monkeypatched: these are unit tests; the real
save path is covered by the live-DB runs recorded in the scraper's
commit history.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import job_market_intel.scrapers.jobinja.pipeline as pipeline_module
from job_market_intel.scrapers.jobinja.exceptions import JobinjaResponseError
from job_market_intel.scrapers.jobinja.pipeline import JobinjaPipeline


@contextmanager
def _fake_session() -> Any:
    """Stand-in for ``db.session.get_session``: no connection, ever."""
    yield object()


class FakeClient:
    """Records how the pipeline called ``fetch_raw_jobs``."""

    def __init__(self, records: list[dict] | None = None) -> None:
        self.records = records if records is not None else []
        self.calls = 0

    def fetch_raw_jobs(self) -> list[dict]:
        self.calls += 1
        if isinstance(self.records, Exception):
            raise self.records
        return list(self.records)


class FakeRepository:
    def get_source_id_by_code(self, session: Any, code: str) -> int:
        assert code == "jobinja", f"unexpected source code {code!r}"
        return 42

    def create_scraping_session(self, session: Any, *, source_id: int, trigger_type: str) -> int:
        return 7

    def save_cleaned_jobs(self, **kwargs: Any) -> dict[str, int]:
        return {"inserted": 1, "updated": 0, "unchanged": 0, "failed": 0}

    def finish_scraping_session(self, session: Any, **kwargs: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def persisted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture ``_persist_with_session`` calls so no database is touched.

    Also swaps ``get_session`` for a connectionless stand-in: every
    ``store_db=True`` path opens one, and unit tests must never open a
    real one.
    """
    calls: list[dict[str, Any]] = []

    def fake_persist(self: Any, session: Any, cleaned_jobs: list[Any], raw_count: int, result: Any) -> None:
        calls.append({"cleaned_jobs": cleaned_jobs, "raw_count": raw_count, "result": result})

    monkeypatch.setattr(JobinjaPipeline, "_persist_with_session", fake_persist)
    monkeypatch.setattr(pipeline_module, "get_session", _fake_session)
    return calls


def _pipeline(client: FakeClient) -> JobinjaPipeline:
    return JobinjaPipeline(client=client, repository=FakeRepository())


class TestRunWiring:
    def test_dry_run_never_persists(self, persisted: list[dict[str, Any]]) -> None:
        client = FakeClient()
        pipeline = _pipeline(client)

        result = pipeline.run(store_db=False)

        assert client.calls == 1
        assert result.raw_count == 0
        assert result.session_id is None
        assert persisted == []

    def test_db_run_persists_and_records_session(
        self, persisted: list[dict[str, Any]]
    ) -> None:
        # One raw record whose HTML parses into a real job (minimal
        # JobPosting — enough for parser + cleaner to run end-to-end).
        html = (
            '<html><script type="application/ld+json">'
            '{"@type": "JobPosting", "identifier": {"value": "1118910"},'
            ' "title": "کارشناس فروش", "datePosted": "2026-10-06",'
            ' "hiringOrganization": {"name": "Acme"},'
            ' "baseSalary": {"currency": "IRT", "value": 45000000,'
            ' "unitText": "MONTH"},'
            ' "jobLocation": {"address": {"addressCountry": {"name": "IR"}}}'
            "}</script></html>"
        )
        client = FakeClient([{"url": "https://jobinja.ir/companies/a/jobs/x/y", "html": html}])
        pipeline = _pipeline(client)

        result = pipeline.run(store_db=True)

        assert len(persisted) == 1
        assert persisted[0]["raw_count"] == 1
        assert persisted[0]["result"] is result
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.cleaned_count == 1

    def test_validation_failure_is_reported_not_raised(
        self, persisted: list[dict[str, Any]]
    ) -> None:
        # Zero records → below min_expected (100) → validation FAILED —
        # but the run still completes and persists (the shared stance).
        pipeline = _pipeline(FakeClient())

        result = pipeline.run(store_db=True)

        assert result.validation_passed is False
        assert result.issues
        assert len(persisted) == 1

    def test_client_failure_propagates(self, persisted: list[dict[str, Any]]) -> None:
        client = FakeClient(records=JobinjaResponseError("listing format changed"))
        pipeline = _pipeline(client)

        with pytest.raises(JobinjaResponseError):
            pipeline.run(store_db=True)

        assert client.calls == 1
        assert persisted == []


class TestNoSkipKnown:
    def test_fetch_takes_no_exclusion_argument(self) -> None:
        # The cursor (JOBINGJA_START_PAGE) replaced skip-known for this
        # source — pin it so a future "helpful" exclusion kwarg fails
        # loudly here first.
        import inspect

        from job_market_intel.scrapers.jobinja.client import JobinjaClient

        params = inspect.signature(JobinjaClient.fetch_raw_jobs).parameters
        assert "exclude_ids" not in params

        client = FakeClient()
        _pipeline(client).run(store_db=False)
        # fetch_raw_jobs was called with no arguments at all.
        assert client.calls == 1

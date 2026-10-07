"""Unit tests for JobvisionClient — discovery and detail contracts.

The request loop is covered live (smoke + API probes, 2026-10-07);
these tests pin the logic that is pure once fetching is stubbed:

* sitemap selection — id extraction, dedup, skip-known exclusion,
  window cap, image URLs never matching;
* the empty-selection contract (corpus covered vs. discovery broken);
* ``_fetch_job``'s failure taxonomy — a stale sitemap entry (404/410)
  or soft API failure skips one job, transient exhaustion fails the
  run (the Glints 410 fix, baked in from day one);
* ``_request_json``'s shape-change behavior (non-JSON propagates).
"""

from __future__ import annotations

from typing import Any

import pytest

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.scrapers.jobvision.client import JobvisionClient
from job_market_intel.scrapers.jobvision.config import JobvisionSettings
from job_market_intel.scrapers.jobvision.exceptions import (
    JobvisionFetchError,
    JobvisionResponseError,
)

JOB_1 = "https://jobvision.ir/jobs/73596/استخدام-کارمند-حسابداری"
JOB_1_DUP = "https://jobvision.ir/jobs/73596/duplicate-slug"
JOB_2 = "https://jobvision.ir/jobs/127203/استخدام-کارمند-اداری"
JOB_3 = "https://jobvision.ir/jobs/216383/استخدام-مونتاژ-کار"
LOGO = "https://jobvision.ir/company/logo/1234.jpg"
JOB_IMAGE = "https://jobvision.ir/jobpost/image/99.webp"


def _sitemap_xml(*urls: str) -> str:
    return "<urlset>" + "".join(f"<loc>{u}</loc>" for u in urls) + "</urlset>"


SITEMAP = _sitemap_xml(JOB_1, LOGO, JOB_1_DUP, JOB_2, JOB_IMAGE, JOB_3)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> JobvisionClient:
    """A client whose sitemap fetch is stubbed (window 10, no pacing)."""
    client = JobvisionClient(
        settings=JobvisionSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
    )
    monkeypatch.setattr(client, "_request_text", lambda url, what: SITEMAP)
    return client


class TestSelectJobs:
    def test_selects_unique_job_ids_and_ignores_image_urls(
        self, client: JobvisionClient
    ) -> None:
        selected = dict(client._select_jobs())

        # 73596 twice (dup slug) collapses to one; logo/job-image URLs
        # carry no /jobs/{digits}/ segment and never match.
        assert set(selected) == {
            "73596",
            "127203",
            "216383",
        }
        assert selected["73596"] == JOB_1  # first occurrence wins

    def test_known_ids_are_excluded(self, client: JobvisionClient) -> None:
        selected = dict(client._select_jobs(exclude_ids={"73596", "127203"}))
        assert set(selected) == {"216383"}

    def test_excluding_everything_returns_empty_not_an_error(
        self, client: JobvisionClient
    ) -> None:
        assert client._select_jobs(exclude_ids={"73596", "127203", "216383"}) == []

    def test_window_caps_unique_unseen_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        capped = JobvisionClient(
            settings=JobvisionSettings(max_jobs_per_run=2, fetch_delay_seconds=0)
        )
        monkeypatch.setattr(capped, "_request_text", lambda url, what: SITEMAP)

        selected = dict(capped._select_jobs())
        assert set(selected) == {"73596", "127203"}  # stops at the window


class TestFetchRawJobsContract:
    @pytest.fixture
    def dry_client(self) -> JobvisionClient:
        return JobvisionClient(
            settings=JobvisionSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
        )

    def test_exclusion_is_passed_to_selection(
        self,
        dry_client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_select(exclude_ids: set[str] | None = None) -> list[tuple[str, str]]:
            seen["exclude_ids"] = exclude_ids
            return [("73596", JOB_1)]

        monkeypatch.setattr(dry_client, "_select_jobs", fake_select)
        monkeypatch.setattr(
            dry_client, "_fetch_job", lambda job_id: {"id": job_id, "title": "x"}
        )

        jobs = dry_client.fetch_raw_jobs(exclude_ids={"127203"})

        assert seen["exclude_ids"] == {"127203"}
        assert jobs == [{"url": JOB_1, "payload": {"id": "73596", "title": "x"}}]

    def test_empty_selection_with_exclusion_returns_empty(
        self,
        dry_client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Corpus fully covered: no unseen ids — a successful no-op.
        monkeypatch.setattr(dry_client, "_select_jobs", lambda exclude_ids=None: [])

        assert dry_client.fetch_raw_jobs(exclude_ids={"73596"}) == []

    def test_empty_selection_without_exclusion_raises(
        self,
        dry_client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No exclusion means a fresh scrape; an empty result there is a
        # broken sitemap format, not "nothing new".
        monkeypatch.setattr(dry_client, "_select_jobs", lambda exclude_ids=None: [])

        with pytest.raises(JobvisionResponseError):
            dry_client.fetch_raw_jobs()

    def test_all_jobs_unusable_raises_loudly(
        self,
        dry_client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            dry_client, "_select_jobs", lambda exclude_ids=None: [("73596", JOB_1)]
        )
        monkeypatch.setattr(dry_client, "_fetch_job", lambda job_id: None)

        with pytest.raises(JobvisionResponseError):
            dry_client.fetch_raw_jobs()


class TestDetailUrl:
    def test_job_post_id_query_param(self) -> None:
        client = JobvisionClient()
        assert client._detail_url("1550047") == (
            "https://candidateapi.jobvision.ir/api/v1/JobPost/Detail"
            "?jobPostId=1550047"
        )


def _raise_from(cause: Exception):
    """A ``_request_json`` stand-in failing exactly like the real one.

    The real client raises ``JobvisionFetchError`` *from* the shared
    http_client error, so ``__cause__`` carries the permanent/transient
    distinction the skip logic keys on.
    """

    def _do(url: str, *, what: str) -> dict:
        raise JobvisionFetchError(f"request failed ({what}): {cause}") from cause

    return _do


class TestFetchJobFailureTaxonomy:
    """A stale sitemap entry costs one page, not the run (baked in
    from day one — the Glints 410 fix, commit 64f9901)."""

    @pytest.fixture
    def client(self) -> JobvisionClient:
        return JobvisionClient(
            settings=JobvisionSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
        )

    def test_permanent_http_error_skips_the_job(
        self,
        client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            client, "_request_json", _raise_from(PermanentHTTPError("HTTP 410"))
        )
        assert client._fetch_job("73596") is None

    def test_transient_exhaustion_still_raises(
        self,
        client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A dead link is id-local; retry exhaustion means the *API* is
        # unreachable — that must fail the run.
        monkeypatch.setattr(
            client, "_request_json", _raise_from(TransientHTTPError("HTTP 503"))
        )
        with pytest.raises(JobvisionFetchError):
            client._fetch_job("73596")

    def test_soft_api_failure_skips(
        self,
        client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            client,
            "_request_json",
            lambda url, what: {"isSuccess": False, "message": "یافت نشد"},
        )
        assert client._fetch_job("73596") is None

    def test_success_false_or_missing_data_skips(
        self,
        client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            client, "_request_json", lambda url, what: {"isSuccess": True, "data": None}
        )
        assert client._fetch_job("73596") is None

        monkeypatch.setattr(
            client,
            "_request_json",
            lambda url, what: {"isSuccess": True, "data": {"title": "بدون شناسه"}},
        )
        assert client._fetch_job("73596") is None

    def test_healthy_envelope_returns_data(
        self,
        client: JobvisionClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = {"id": 73596, "title": "کارمند حسابداری"}
        monkeypatch.setattr(
            client,
            "_request_json",
            lambda url, what: {"isSuccess": True, "statusCode": 200, "data": payload},
        )
        assert client._fetch_job("73596") is payload


class TestRequestJson:
    def test_non_json_body_raises_not_skips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A shape change (or bot wall) affects every job — propagating
        # fails the run loudly instead of silently skipping all 400.
        client = JobvisionClient()

        class _Html:
            def json(self) -> Any:
                raise ValueError("Expecting value")

        monkeypatch.setattr(client, "_get", lambda url, what: _Html())

        with pytest.raises(JobvisionFetchError):
            client._request_json("https://x.invalid/", what="job 1")

    def test_non_object_json_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = JobvisionClient()

        class _List:
            def json(self) -> Any:
                return [1, 2, 3]

        monkeypatch.setattr(client, "_get", lambda url, what: _List())

        with pytest.raises(JobvisionFetchError):
            client._request_json("https://x.invalid/", what="job 1")

    def test_object_json_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = JobvisionClient()

        class _Ok:
            def json(self) -> Any:
                return {"isSuccess": True, "data": {"id": 1}}

        monkeypatch.setattr(client, "_get", lambda url, what: _Ok())

        assert client._request_json("https://x.invalid/", what="job 1") == {
            "isSuccess": True,
            "data": {"id": 1},
        }

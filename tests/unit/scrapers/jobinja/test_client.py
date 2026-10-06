"""Unit tests for JobinjaClient discovery — listing extraction/selection.

The client's request loop is covered live (smoke run, 2026-10-07);
these tests pin the *selection* logic, which is pure once listing
fetches are stubbed: card-link extraction with tracking-param stripping
and de-duplication, window pagination across pages, the start_page
offset, and the empty-discovery contract (broken site vs. end of walk).
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.jobinja.client import JobinjaClient
from job_market_intel.scrapers.jobinja.config import JobinjaSettings
from job_market_intel.scrapers.jobinja.exceptions import JobinjaResponseError

_URL_A = "https://jobinja.ir/companies/acme/jobs/aaaa/first"
_URL_B = "https://jobinja.ir/companies/beta/jobs/bbbb/second"
_URL_C = "https://jobinja.ir/companies/gamma/jobs/cccc/third"


def _listing(*urls: str) -> str:
    """Listing HTML: each job appears twice (title + logo links), some with tracking params."""
    cards = []
    for url in urls:
        cards.append(f'<a href="{url}?_ref=listing&_t=1791334000">title</a>')
        cards.append(f'<a href="{url}">logo</a>')
    return "<html><body>" + "".join(cards) + "</body></html>"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> JobinjaClient:
    """A client whose listing fetches are stubbed: pages 1-3, empty after."""
    client = JobinjaClient(settings=JobinjaSettings(max_jobs_per_run=10, fetch_delay_seconds=0))
    pages = {
        1: _listing(_URL_A, _URL_B),
        2: _listing(_URL_C),
    }
    requested: list[int] = []

    def fake_request(url: str, *, what: str) -> str:
        page = int(url.rsplit("=", 1)[-1])
        requested.append(page)
        return pages.get(page, "<html><body></body></html>")

    monkeypatch.setattr(client, "_request_text", fake_request)
    client.requested_pages = requested  # type: ignore[attr-defined]
    return client


class TestExtractJobUrls:
    def test_strips_tracking_params_and_deduplicates(self) -> None:
        html = _listing(_URL_A, _URL_B)
        assert JobinjaClient._extract_job_urls(html) == [_URL_A, _URL_B]

    def test_non_job_links_are_ignored(self) -> None:
        html = (
            '<a href="https://jobinja.ir/companies/acme">company</a>'
            '<a href="https://jobinja.ir/companies/acme/jobs">all jobs</a>'
            '<a href="https://jobinja.ir/jobs?page=2">next page</a>'
            f'<a href="{_URL_A}">the actual job</a>'
        )
        assert JobinjaClient._extract_job_urls(html) == [_URL_A]

    def test_empty_listing_yields_empty_list(self) -> None:
        assert JobinjaClient._extract_job_urls("<html>nothing here</html>") == []


class TestSelectJobUrls:
    def test_fills_window_across_pages_and_stops_at_end(self, client: JobinjaClient) -> None:
        selected = client._select_job_urls()
        assert selected == [_URL_A, _URL_B, _URL_C]
        # Window 10 never fills (page 3 is empty), so the walk stops there.
        assert client.requested_pages == [1, 2, 3]  # type: ignore[attr-defined]

    def test_window_bounds_the_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = JobinjaClient(
            settings=JobinjaSettings(max_jobs_per_run=1, fetch_delay_seconds=0)
        )
        monkeypatch.setattr(
            client,
            "_request_text",
            lambda url, what: _listing(_URL_A, _URL_B),
        )
        assert client._select_job_urls() == [_URL_A]

    def test_start_page_offsets_the_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = JobinjaClient(
            settings=JobinjaSettings(max_jobs_per_run=10, start_page=900,
                                     fetch_delay_seconds=0)
        )
        monkeypatch.setattr(
            client,
            "_request_text",
            lambda url, what: _listing(_URL_B) if "page=900" in url else "",
        )
        assert client._select_job_urls() == [_URL_B]

    def test_beyond_end_of_listing_returns_empty(self, client: JobinjaClient) -> None:
        # start_page past page 3 (empty everywhere): selection is empty —
        # fetch_raw_jobs turns that into JobinjaResponseError.
        client._settings.start_page = 4  # type: ignore[attr-defined]
        assert client._select_job_urls() == []


class TestFetchRawJobsContract:
    @pytest.fixture
    def dry_client(self, monkeypatch: pytest.MonkeyPatch) -> JobinjaClient:
        return JobinjaClient(
            settings=JobinjaSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
        )

    def test_empty_discovery_raises(
        self,
        dry_client: JobinjaClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No exclusion set exists for Jobinja, so an empty listing is a
        # broken site/format (or a start_page past the end) — never a
        # silent "nothing new" no-op.
        monkeypatch.setattr(dry_client, "_select_job_urls", lambda: [])

        with pytest.raises(JobinjaResponseError):
            dry_client.fetch_raw_jobs()

    def test_dead_detail_page_is_skipped_not_fatal(
        self,
        dry_client: JobinjaClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(dry_client, "_select_job_urls", lambda: [_URL_A, _URL_B, _URL_C])
        monkeypatch.setattr(
            dry_client,
            "_fetch_job",
            lambda url: None if url == _URL_B else f"<html>{url}</html>",
        )

        jobs = dry_client.fetch_raw_jobs()
        assert [j["url"] for j in jobs] == [_URL_A, _URL_C]

    def test_every_detail_page_failing_raises(
        self,
        dry_client: JobinjaClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(dry_client, "_select_job_urls", lambda: [_URL_A])
        monkeypatch.setattr(dry_client, "_fetch_job", lambda url: None)

        with pytest.raises(JobinjaResponseError):
            dry_client.fetch_raw_jobs()

    def test_records_carry_url_and_html(
        self,
        dry_client: JobinjaClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(dry_client, "_select_job_urls", lambda: [_URL_A])
        monkeypatch.setattr(dry_client, "_fetch_job", lambda url: "<html>job</html>")

        jobs = dry_client.fetch_raw_jobs()
        assert jobs == [{"url": _URL_A, "html": "<html>job</html>"}]

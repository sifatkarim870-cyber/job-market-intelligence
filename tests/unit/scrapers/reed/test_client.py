"""Unit tests for job_market_intel.scrapers.reed.client.ReedClient.

``fetch_json`` is monkeypatched at ``job_market_intel.scrapers.reed.client.fetch_json``
rather than making real network calls — same approach
``scrapers/remotive/test_client.py``/``scrapers/remoteok/test_client.py``
already use. Reed-specific additions: verifying the Basic Auth tuple is
actually passed on every call (no other source needs this), and the
Search/Details two-endpoint pagination/aggregation behavior neither
RemoteOK nor Remotive has at all.
"""

from __future__ import annotations

import pytest

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.scrapers.reed.client import ReedClient
from job_market_intel.scrapers.reed.config import ReedSettings
from job_market_intel.scrapers.reed.exceptions import (
    ReedAuthenticationError,
    ReedFetchError,
    ReedResponseError,
)
from job_market_intel.scrapers.reed.search_queries import ReedSearchQuery

FAST_SETTINGS = ReedSettings(
    api_key="test-key",
    max_retry_attempts=2,
    retry_initial_wait_seconds=0.01,
    retry_max_wait_seconds=0.02,
    request_timeout_seconds=1.0,
    results_per_page=2,
    max_search_pages_per_query=3,
)

JOB_A = {"jobId": 1, "jobTitle": "Engineer"}
JOB_B = {"jobId": 2, "jobTitle": "Designer"}


class TestAuthIsAlwaysSent:
    def test_basic_auth_tuple_uses_api_key_as_username_and_empty_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            captured.update(kwargs)
            return {"results": [], "totalResults": 0}

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        client.fetch_search_page(ReedSearchQuery(keywords="data scientist"))

        assert captured["auth"] == ("test-key", "")

    def test_details_call_also_sends_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            captured.update(kwargs)
            return {"jobId": 1}

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        client.fetch_job_details("1")

        assert captured["auth"] == ("test-key", "")


class TestFetchSearchPageUrlBuilding:
    def test_includes_keywords_and_location_when_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_urls: list[str] = []

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            captured_urls.append(url)
            return {"results": [], "totalResults": 0}

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        client.fetch_search_page(
            ReedSearchQuery(keywords="data scientist", location_name="London"),
            results_to_skip=0,
        )

        url = captured_urls[0]
        assert "keywords=data%20scientist" in url
        assert "locationName=London" in url
        assert "resultsToTake=2" in url
        assert "resultsToSkip=0" in url

    def test_omits_keywords_and_location_when_not_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_urls: list[str] = []

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            captured_urls.append(url)
            return {"results": [], "totalResults": 0}

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        client.fetch_search_page(ReedSearchQuery())

        assert "keywords=" not in captured_urls[0]
        assert "locationName=" not in captured_urls[0]


class TestFetchSearchPageResponseValidation:
    def test_returns_results_and_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.reed.client.fetch_json",
            lambda *a, **k: {"results": [JOB_A, JOB_B], "totalResults": 2},
        )
        client = ReedClient(settings=FAST_SETTINGS)
        results, total = client.fetch_search_page(ReedSearchQuery())
        assert results == [JOB_A, JOB_B]
        assert total == 2

    def test_non_dict_response_raises_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.reed.client.fetch_json", lambda *a, **k: [1, 2, 3]
        )
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedResponseError):
            client.fetch_search_page(ReedSearchQuery())

    def test_missing_results_key_raises_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.reed.client.fetch_json",
            lambda *a, **k: {"totalResults": 0},
        )
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedResponseError):
            client.fetch_search_page(ReedSearchQuery())

    def test_missing_total_results_raises_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.reed.client.fetch_json",
            lambda *a, **k: {"results": []},
        )
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedResponseError):
            client.fetch_search_page(ReedSearchQuery())


class TestFetchSearchResultsPagination:
    def test_pages_until_total_results_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pages = [
            {"results": [JOB_A, JOB_B], "totalResults": 3},
            {"results": [{"jobId": 3}], "totalResults": 3},
        ]

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            return pages.pop(0)

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        results = client.fetch_search_results(ReedSearchQuery(keywords="x"))

        assert len(results) == 3
        assert pages == []  # both pages were consumed, no more, no fewer

    def test_stops_on_empty_page_even_if_total_not_reached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pages = [{"results": [JOB_A], "totalResults": 100}, {"results": [], "totalResults": 100}]

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            return pages.pop(0) if pages else {"results": [JOB_B], "totalResults": 100}

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        results = client.fetch_search_results(ReedSearchQuery(keywords="x"))

        assert results == [JOB_A]

    def test_respects_max_search_pages_per_query_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # totalResults claims far more than the cap allows fetching.
        monkeypatch.setattr(
            "job_market_intel.scrapers.reed.client.fetch_json",
            lambda *a, **k: {"results": [JOB_A, JOB_B], "totalResults": 100000},
        )
        client = ReedClient(settings=FAST_SETTINGS)  # cap = 3 pages, 2 per page
        results = client.fetch_search_results(ReedSearchQuery(keywords="x"))

        assert len(results) == 6  # 3 pages * 2 results, then stopped


class TestFetchJobDetails:
    def test_builds_url_with_job_id_appended(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_urls: list[str] = []

        def fake_fetch_json(url: str, **kwargs: object) -> dict:
            captured_urls.append(url)
            return {"jobId": 42}

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", fake_fetch_json)
        client = ReedClient(settings=FAST_SETTINGS)
        client.fetch_job_details("42")

        assert captured_urls[0] == "https://www.reed.co.uk/api/1.0/jobs/42"

    def test_missing_job_id_in_response_raises_response_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.reed.client.fetch_json", lambda *a, **k: {"foo": "bar"}
        )
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedResponseError):
            client.fetch_job_details("42")


class TestErrorClassification:
    def test_401_is_classified_as_authentication_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_401(*a: object, **k: object) -> None:
            raise PermanentHTTPError("returned client error status 401: 'Unauthorized'")

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", raise_401)
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedAuthenticationError):
            client.fetch_job_details("1")

    def test_403_is_classified_as_authentication_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_403(*a: object, **k: object) -> None:
            raise PermanentHTTPError("returned client error status 403: 'Forbidden'")

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", raise_403)
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedAuthenticationError):
            client.fetch_job_details("1")

    def test_other_permanent_error_is_classified_as_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_404(*a: object, **k: object) -> None:
            raise PermanentHTTPError("returned client error status 404: 'Not Found'")

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", raise_404)
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedFetchError):
            client.fetch_job_details("1")

    def test_transient_error_exhausting_retries_is_classified_as_fetch_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def always_transient(*a: object, **k: object) -> None:
            raise TransientHTTPError("returned 429 (rate limited)")

        monkeypatch.setattr("job_market_intel.scrapers.reed.client.fetch_json", always_transient)
        client = ReedClient(settings=FAST_SETTINGS)
        with pytest.raises(ReedFetchError):
            client.fetch_job_details("1")

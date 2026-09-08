"""Unit tests for job_market_intel.scrapers.remotive.client.RemotiveClient.

Mirrors ``scrapers/remoteok/test_client.py``'s approach exactly — see that
module's docstring for why ``fetch_json`` is replaced rather than making
real network calls, and why retry settings use near-zero wait times.

The one genuine difference from RemoteOK's client tests: Remotive's
response shape is a dict with a ``jobs`` key, not a bare list, so the
response-shape tests here are written against that shape, not adapted
from RemoteOK's list-shape tests.
"""

from __future__ import annotations

import pytest

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.scrapers.remotive.client import RemotiveClient
from job_market_intel.scrapers.remotive.config import RemotiveSettings
from job_market_intel.scrapers.remotive.exceptions import RemotiveFetchError, RemotiveResponseError

FAST_TEST_SETTINGS = RemotiveSettings(
    max_retry_attempts=3,
    retry_initial_wait_seconds=0.01,
    retry_max_wait_seconds=0.02,
    request_timeout_seconds=1.0,
)

VALID_JOB_1 = {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
VALID_JOB_2 = {"id": 2, "title": "Designer", "company_name": "Globex", "url": "https://x.test/2"}


class TestFetchRawJobsSuccess:
    def test_returns_job_records_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: {"job-count": 2, "jobs": [VALID_JOB_1, VALID_JOB_2]},
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()
        assert result == [VALID_JOB_1, VALID_JOB_2]

    def test_default_settings_are_used_when_none_provided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: {"job-count": 1, "jobs": [VALID_JOB_1]},
        )
        client = RemotiveClient()  # no settings passed
        result = client.fetch_raw_jobs()
        assert result == [VALID_JOB_1]


class TestFetchRawJobsRetryBehavior:
    def test_retries_on_transient_error_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def flaky_fetch_json(*args: object, **kwargs: object) -> dict:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise TransientHTTPError("simulated temporary network failure")
            return {"job-count": 1, "jobs": [VALID_JOB_1]}

        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json", flaky_fetch_json
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()

        assert result == [VALID_JOB_1]
        assert call_count["n"] == 3, "Expected exactly 2 failures + 1 successful final attempt"

    def test_raises_fetch_error_after_exhausting_all_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def always_fails(*args: object, **kwargs: object) -> dict:
            call_count["n"] += 1
            raise TransientHTTPError("simulated permanent-feeling network failure")

        monkeypatch.setattr("job_market_intel.scrapers.remotive.client.fetch_json", always_fails)
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)

        with pytest.raises(RemotiveFetchError):
            client.fetch_raw_jobs()

        assert call_count["n"] == FAST_TEST_SETTINGS.max_retry_attempts, (
            "Should attempt exactly max_retry_attempts times, no more, no fewer"
        )

    def test_permanent_error_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def permanent_failure(*args: object, **kwargs: object) -> dict:
            call_count["n"] += 1
            raise PermanentHTTPError("simulated 404")

        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json", permanent_failure
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)

        with pytest.raises(RemotiveFetchError):
            client.fetch_raw_jobs()

        assert call_count["n"] == 1, "A permanent error must not be retried"


class TestFetchRawJobsResponseShapeValidation:
    def test_raises_response_error_when_response_is_not_a_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: [VALID_JOB_1, VALID_JOB_2],  # a bare list, not a dict
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemotiveResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_when_jobs_key_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: {"job-count": 0},  # no "jobs" key at all
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemotiveResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_when_jobs_is_not_a_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: {"jobs": "not-a-list"},
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemotiveResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_on_completely_empty_jobs_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: {"job-count": 0, "jobs": []},
        )
        client = RemotiveClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemotiveResponseError):
            client.fetch_raw_jobs()

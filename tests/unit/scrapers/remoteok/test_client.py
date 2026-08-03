"""Unit tests for job_market_intel.scrapers.remoteok.client.RemoteOKClient.

These tests never make a real network call. Instead, they replace
``fetch_json`` (as imported into ``client.py``'s own namespace) with a fake
implementation, so we can deterministically simulate RemoteOK's feed
behaving well, behaving badly, or failing outright — without depending on
RemoteOK's actual server being up, and without tests taking real seconds to
run through real HTTP timeouts.

Retry settings are deliberately configured with near-zero wait times in
every test (`retry_initial_wait_seconds=0.01`) so tests that intentionally
trigger retries stay fast, while still exercising the real retry logic in
``src/common/retry.py`` rather than mocking that away too.
"""

from __future__ import annotations

import pytest

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.scrapers.remoteok.client import RemoteOKClient
from job_market_intel.scrapers.remoteok.config import RemoteOKSettings
from job_market_intel.scrapers.remoteok.exceptions import RemoteOKFetchError, RemoteOKResponseError

FAST_TEST_SETTINGS = RemoteOKSettings(
    max_retry_attempts=3,
    retry_initial_wait_seconds=0.01,
    retry_max_wait_seconds=0.02,
    request_timeout_seconds=1.0,
)

METADATA_ENTRY = {"legal": "https://remoteok.com/legal"}
VALID_JOB_1 = {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
VALID_JOB_2 = {"id": "2", "position": "Designer", "company": "Globex", "url": "https://x.test/2"}


class TestFetchRawJobsSuccess:
    def test_returns_job_records_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remoteok.client.fetch_json",
            lambda *args, **kwargs: [METADATA_ENTRY, VALID_JOB_1, VALID_JOB_2],
        )
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()
        assert result == [VALID_JOB_1, VALID_JOB_2]

    def test_filters_out_non_job_metadata_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remoteok.client.fetch_json",
            lambda *args, **kwargs: [METADATA_ENTRY, VALID_JOB_1],
        )
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()
        assert METADATA_ENTRY not in result
        assert all("id" in record for record in result)

    def test_default_settings_are_used_when_none_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remoteok.client.fetch_json",
            lambda *args, **kwargs: [VALID_JOB_1],
        )
        client = RemoteOKClient()  # no settings passed
        result = client.fetch_raw_jobs()
        assert result == [VALID_JOB_1]


class TestFetchRawJobsRetryBehavior:
    def test_retries_on_transient_error_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def flaky_fetch_json(*args: object, **kwargs: object) -> list[dict]:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise TransientHTTPError("simulated temporary network failure")
            return [VALID_JOB_1]

        monkeypatch.setattr("job_market_intel.scrapers.remoteok.client.fetch_json", flaky_fetch_json)
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()

        assert result == [VALID_JOB_1]
        assert call_count["n"] == 3, "Expected exactly 2 failures + 1 successful final attempt"

    def test_raises_fetch_error_after_exhausting_all_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def always_fails(*args: object, **kwargs: object) -> list[dict]:
            call_count["n"] += 1
            raise TransientHTTPError("simulated permanent-feeling network failure")

        monkeypatch.setattr("job_market_intel.scrapers.remoteok.client.fetch_json", always_fails)
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)

        with pytest.raises(RemoteOKFetchError):
            client.fetch_raw_jobs()

        assert call_count["n"] == FAST_TEST_SETTINGS.max_retry_attempts, (
            "Should attempt exactly max_retry_attempts times, no more, no fewer"
        )

    def test_permanent_error_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def permanent_failure(*args: object, **kwargs: object) -> list[dict]:
            call_count["n"] += 1
            raise PermanentHTTPError("simulated 404")

        monkeypatch.setattr("job_market_intel.scrapers.remoteok.client.fetch_json", permanent_failure)
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)

        with pytest.raises(RemoteOKFetchError):
            client.fetch_raw_jobs()

        assert call_count["n"] == 1, "A permanent error must not be retried"


class TestFetchRawJobsResponseShapeValidation:
    def test_raises_response_error_when_response_is_not_a_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remoteok.client.fetch_json",
            lambda *args, **kwargs: {"unexpected": "shape"},
        )
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemoteOKResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_when_zero_job_records_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remoteok.client.fetch_json",
            lambda *args, **kwargs: [METADATA_ENTRY],  # only the non-job entry, no real jobs
        )
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemoteOKResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_on_completely_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.remoteok.client.fetch_json",
            lambda *args, **kwargs: [],
        )
        client = RemoteOKClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(RemoteOKResponseError):
            client.fetch_raw_jobs()

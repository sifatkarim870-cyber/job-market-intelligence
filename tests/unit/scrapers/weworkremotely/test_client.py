"""Unit tests for job_market_intel.scrapers.weworkremotely.client.WWRClient.

Mirrors ``scrapers/remoteok/test_client.py``'s approach exactly: no real
network call is ever made — ``fetch_html`` (as imported into ``client.py``'s
own namespace) is replaced with a fake implementation, so WWR's feed
behaving well, badly, or failing outright can be simulated
deterministically. Retry settings use near-zero wait times so tests that
intentionally trigger retries stay fast while still exercising the real
retry logic in ``common/retry.py``.

Genuinely new coverage beyond what RemoteOK's client tests needed:
XML parsing (malformed XML must raise, not crash), namespace-qualified
``<media:content>`` extraction, and empty-element-to-``None`` normalization
— none of these exist for RemoteOK's JSON-based client.
"""

from __future__ import annotations

import pytest

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.scrapers.weworkremotely.client import WWRClient
from job_market_intel.scrapers.weworkremotely.config import WWRSettings
from job_market_intel.scrapers.weworkremotely.exceptions import WWRFetchError, WWRResponseError

FAST_TEST_SETTINGS = WWRSettings(
    max_retry_attempts=3,
    retry_initial_wait_seconds=0.01,
    retry_max_wait_seconds=0.02,
    request_timeout_seconds=1.0,
)


def _rss(*items: str) -> str:
    """Wrap one or more raw ``<item>...</item>`` blocks in a full RSS document."""
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss">'
        f"<channel><title>We Work Remotely</title>{body}</channel></rss>"
    )


VALID_ITEM_1 = """
<item>
<title>Acme Corp: Backend Engineer</title>
<region>Anywhere in the World</region>
<country></country>
<state>Texas</state>
<skills>Python, Django</skills>
<category>Programming</category>
<type>Full-Time</type>
<description><![CDATA[<p>Do engineering.</p>]]></description>
<pubDate>Tue, 25 Aug 2026 07:31:11 +0000</pubDate>
<expires_at>Thu, 24 Sep 2026 07:31:11 +0000</expires_at>
<guid>https://weworkremotely.com/remote-jobs/acme-corp-backend-engineer</guid>
<link>https://weworkremotely.com/remote-jobs/acme-corp-backend-engineer</link>
<media:content url="https://example.com/logo.png" type="image/png"/>
</item>
"""

VALID_ITEM_2_NO_MEDIA = """
<item>
<title>Globex: Frontend Engineer</title>
<region>Anywhere in the World</region>
<skills></skills>
<guid>https://weworkremotely.com/remote-jobs/globex-frontend-engineer</guid>
<link>https://weworkremotely.com/remote-jobs/globex-frontend-engineer</link>
</item>
"""


class TestFetchRawJobsSuccess:
    def test_returns_one_dict_per_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_1, VALID_ITEM_2_NO_MEDIA),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()
        assert len(result) == 2

    def test_extracts_title_guid_link_correctly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_1),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        record = client.fetch_raw_jobs()[0]
        assert record["title"] == "Acme Corp: Backend Engineer"
        assert record["guid"] == "https://weworkremotely.com/remote-jobs/acme-corp-backend-engineer"
        assert record["link"] == "https://weworkremotely.com/remote-jobs/acme-corp-backend-engineer"

    def test_extracts_namespaced_media_content_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_1),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        record = client.fetch_raw_jobs()[0]
        assert record["media_content_url"] == "https://example.com/logo.png"

    def test_missing_media_content_element_yields_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_2_NO_MEDIA),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        record = client.fetch_raw_jobs()[0]
        assert record["media_content_url"] is None

    def test_empty_element_normalizes_to_none_not_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # <country></country> in VALID_ITEM_1 is present but empty.
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_1),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        record = client.fetch_raw_jobs()[0]
        assert record["country"] is None

    def test_missing_element_entirely_also_yields_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # VALID_ITEM_2_NO_MEDIA has no <state> tag at all.
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_2_NO_MEDIA),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        record = client.fetch_raw_jobs()[0]
        assert record["state"] is None

    def test_cdata_wrapped_description_is_extracted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_1),
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        record = client.fetch_raw_jobs()[0]
        assert record["description"] == "<p>Do engineering.</p>"

    def test_default_settings_are_used_when_none_provided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(VALID_ITEM_1),
        )
        client = WWRClient()  # no settings passed
        result = client.fetch_raw_jobs()
        assert len(result) == 1


class TestFetchRawJobsRetryBehavior:
    def test_retries_on_transient_error_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def flaky_fetch_html(*args: object, **kwargs: object) -> str:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise TransientHTTPError("simulated temporary network failure")
            return _rss(VALID_ITEM_1)

        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html", flaky_fetch_html
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        result = client.fetch_raw_jobs()

        assert len(result) == 1
        assert call_count["n"] == 3, "Expected exactly 2 failures + 1 successful final attempt"

    def test_raises_fetch_error_after_exhausting_all_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = {"n": 0}

        def always_fails(*args: object, **kwargs: object) -> str:
            call_count["n"] += 1
            raise TransientHTTPError("simulated permanent-feeling network failure")

        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html", always_fails
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)

        with pytest.raises(WWRFetchError):
            client.fetch_raw_jobs()

        assert call_count["n"] == FAST_TEST_SETTINGS.max_retry_attempts, (
            "Should attempt exactly max_retry_attempts times, no more, no fewer"
        )

    def test_permanent_error_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def permanent_failure(*args: object, **kwargs: object) -> str:
            call_count["n"] += 1
            raise PermanentHTTPError("simulated 404")

        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html", permanent_failure
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)

        with pytest.raises(WWRFetchError):
            client.fetch_raw_jobs()

        assert call_count["n"] == 1, "A permanent error must not be retried"


class TestFetchRawJobsResponseShapeValidation:
    def test_raises_response_error_on_malformed_xml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: "<rss><channel><item><title>unterminated",
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(WWRResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_when_zero_items_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: _rss(),  # valid RSS, but no <item> entries
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(WWRResponseError):
            client.fetch_raw_jobs()

    def test_raises_response_error_on_completely_non_xml_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "job_market_intel.scrapers.weworkremotely.client.fetch_html",
            lambda *args, **kwargs: "this is not xml at all, just plain text",
        )
        client = WWRClient(settings=FAST_TEST_SETTINGS)
        with pytest.raises(WWRResponseError):
            client.fetch_raw_jobs()

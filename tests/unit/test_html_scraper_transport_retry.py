"""A dropped connection is retried; an HTTP error status is not.

minajobs.net intermittently closes the TLS connection (``Connection closed
abruptly``) or times out while answering the same URL with 200 on the next
attempt. The listing page does not get a second chance elsewhere in the
pipeline, so one dropped request used to turn into a whole empty run (CI
run 40867693287, 2026-10-29). ``_get`` now retries transport failures a
bounded number of times.

These tests pin both halves of that rule: a transport failure is retried, and
a 5xx response (where the server *did* answer) is not.
"""

from __future__ import annotations

import pytest
import requests

from job_market_intel.scrapers.html_scraper import client as client_module
from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.exceptions import HtmlScraperFetchError


def _client() -> HtmlScraperClient:
    return HtmlScraperClient(
        source_code="unit_test",
        site_config=SiteConfig(
            source_code="unit_test",
            source_name="Unit test board",
            country="Nowhere",
            base_url="https://example.invalid",
        ),
    )


def _response(body: bytes = b"ok", status: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers["content-type"] = "text/html; charset=utf-8"
    resp.encoding = "utf-8"
    resp.url = "https://example.invalid/jobs"
    return resp


def test_get_retries_a_dropped_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    calls = {"n": 0}

    def flaky(method, url, headers=None, data=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("Connection closed abruptly")
        return _response(b"<html>ok</html>")

    monkeypatch.setattr(client, "_transport", flaky)
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    assert client._get("https://example.invalid/jobs") == "<html>ok</html>"
    assert calls["n"] == 3


def test_get_gives_up_after_the_attempt_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    calls = {"n": 0}

    def always_times_out(method, url, headers=None, data=None):
        calls["n"] += 1
        raise requests.Timeout("timed out")

    monkeypatch.setattr(client, "_transport", always_times_out)
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(HtmlScraperFetchError):
        client._get("https://example.invalid/jobs")

    assert calls["n"] == client_module._TRANSPORT_ATTEMPTS


def test_http_error_status_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    calls = {"n": 0}

    def server_error(method, url, headers=None, data=None):
        calls["n"] += 1
        return _response(b"boom", status=500)

    monkeypatch.setattr(client, "_transport", server_error)
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(HtmlScraperFetchError):
        client._get("https://example.invalid/jobs")

    assert calls["n"] == 1

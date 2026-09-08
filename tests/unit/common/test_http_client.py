"""Unit tests for job_market_intel.common.http_client.fetch_json.

What these tests verify, and why each matters:
    - A normal 2xx JSON response is parsed and returned correctly.
    - The User-Agent and Accept headers are actually sent (not just
      documented) — this is the fix for the "some sites silently reject
      requests with no User-Agent" gotcha flagged during planning.
    - Network-level failures (connection errors, timeouts) and HTTP 5xx
      responses are classified as TransientHTTPError — these are the
      failure modes retry.py is told to retry.
    - HTTP 4xx responses and invalid-JSON 2xx responses are classified as
      PermanentHTTPError — these must NOT be retried, since retrying won't
      fix a bad URL or a malformed response.

No real network calls are made; ``requests.get`` is replaced with a fake
implementation for every test.
"""

from __future__ import annotations

import pytest
import requests

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
    fetch_json,
)


class _FakeResponse:
    """Minimal stand-in for requests.Response, only implementing what fetch_json uses."""

    def __init__(
        self,
        status_code: int,
        json_data: object = None,
        text: str = "",
        raise_on_json: bool = False,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._raise_on_json = raise_on_json

    def json(self) -> object:
        if self._raise_on_json:
            raise ValueError("simulated invalid JSON body")
        return self._json_data


class TestFetchJsonSuccess:
    def test_returns_parsed_json_on_200(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(200, json_data=[{"id": "1"}]),
        )
        result = fetch_json("https://example.test/api")
        assert result == [{"id": "1"}]

    def test_sends_user_agent_and_accept_headers(self, monkeypatch) -> None:
        captured_kwargs = {}

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            captured_kwargs.update(kwargs)
            return _FakeResponse(200, json_data={})

        monkeypatch.setattr("job_market_intel.common.http_client.requests.get", fake_get)
        fetch_json("https://example.test/api", user_agent="MyTestAgent/1.0")

        headers = captured_kwargs.get("headers", {})
        assert headers.get("User-Agent") == "MyTestAgent/1.0"
        assert headers.get("Accept") == "application/json"

    def test_extra_headers_are_merged_in(self, monkeypatch) -> None:
        captured_kwargs = {}

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            captured_kwargs.update(kwargs)
            return _FakeResponse(200, json_data={})

        monkeypatch.setattr("job_market_intel.common.http_client.requests.get", fake_get)
        fetch_json("https://example.test/api", extra_headers={"X-Custom": "value"})

        headers = captured_kwargs.get("headers", {})
        assert headers.get("X-Custom") == "value"
        assert headers.get("Accept") == "application/json", (
            "Default headers must survive merging extras in"
        )

    def test_timeout_seconds_is_passed_through(self, monkeypatch) -> None:
        captured_kwargs = {}

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            captured_kwargs.update(kwargs)
            return _FakeResponse(200, json_data={})

        monkeypatch.setattr("job_market_intel.common.http_client.requests.get", fake_get)
        fetch_json("https://example.test/api", timeout_seconds=42.0)
        assert captured_kwargs.get("timeout") == 42.0


class TestFetchJsonTransientFailures:
    def test_connection_error_raises_transient(self, monkeypatch) -> None:
        def raise_connection_error(*args: object, **kwargs: object) -> None:
            raise requests.ConnectionError("simulated connection refused")

        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get", raise_connection_error
        )
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected TransientHTTPError to be raised")
        except TransientHTTPError:
            pass

    def test_timeout_raises_transient(self, monkeypatch) -> None:
        def raise_timeout(*args: object, **kwargs: object) -> None:
            raise requests.Timeout("simulated timeout")

        monkeypatch.setattr("job_market_intel.common.http_client.requests.get", raise_timeout)
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected TransientHTTPError to be raised")
        except TransientHTTPError:
            pass

    def test_500_response_raises_transient(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(500, text="Internal Server Error"),
        )
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected TransientHTTPError to be raised")
        except TransientHTTPError:
            pass

    def test_503_response_raises_transient(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(503, text="Service Unavailable"),
        )
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected TransientHTTPError to be raised")
        except TransientHTTPError:
            pass


class TestFetchJsonPermanentFailures:
    def test_404_response_raises_permanent(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(404, text="Not Found"),
        )
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected PermanentHTTPError to be raised")
        except PermanentHTTPError:
            pass

    def test_400_response_raises_permanent(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(400, text="Bad Request"),
        )
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected PermanentHTTPError to be raised")
        except PermanentHTTPError:
            pass

    def test_invalid_json_on_200_raises_permanent(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(
                200, raise_on_json=True, text="<html>not json</html>"
            ),
        )
        try:
            fetch_json("https://example.test/api")
            pytest.fail("Expected PermanentHTTPError to be raised")
        except PermanentHTTPError:
            pass


class TestFetchHtmlSuccess:
    """fetch_html added for aijobs.net (Step 6, second scraper) - see its
    docstring in http_client.py for why this lives here rather than in
    that scraper's own package."""

    def test_returns_response_text_on_200(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(200, text="<html><body>Hello</body></html>"),
        )
        result = fetch_html("https://example.test/listing")
        assert result == "<html><body>Hello</body></html>"

    def test_does_not_attempt_json_parsing(self, monkeypatch) -> None:
        # A response whose .json() would blow up must not matter to fetch_html at all.
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(200, text="not json at all", raise_on_json=True),
        )
        assert fetch_html("https://example.test/listing") == "not json at all"

    def test_sends_user_agent_and_html_accept_header(self, monkeypatch) -> None:
        captured_kwargs = {}

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            captured_kwargs.update(kwargs)
            return _FakeResponse(200, text="<html></html>")

        monkeypatch.setattr("job_market_intel.common.http_client.requests.get", fake_get)
        fetch_html("https://example.test/listing", user_agent="MyTestAgent/1.0")

        headers = captured_kwargs.get("headers", {})
        assert headers.get("User-Agent") == "MyTestAgent/1.0"
        assert headers.get("Accept") == "text/html"

    def test_timeout_seconds_is_passed_through(self, monkeypatch) -> None:
        captured_kwargs = {}

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            captured_kwargs.update(kwargs)
            return _FakeResponse(200, text="<html></html>")

        monkeypatch.setattr("job_market_intel.common.http_client.requests.get", fake_get)
        fetch_html("https://example.test/listing", timeout_seconds=42.0)
        assert captured_kwargs.get("timeout") == 42.0


class TestFetchHtmlTransientFailures:
    def test_connection_error_raises_transient(self, monkeypatch) -> None:
        def raise_connection_error(*args: object, **kwargs: object) -> None:
            raise requests.ConnectionError("simulated connection refused")

        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get", raise_connection_error
        )
        try:
            fetch_html("https://example.test/listing")
            pytest.fail("Expected TransientHTTPError to be raised")
        except TransientHTTPError:
            pass

    def test_500_response_raises_transient(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(500, text="Internal Server Error"),
        )
        try:
            fetch_html("https://example.test/listing")
            pytest.fail("Expected TransientHTTPError to be raised")
        except TransientHTTPError:
            pass


class TestFetchHtmlPermanentFailures:
    def test_404_response_raises_permanent(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "job_market_intel.common.http_client.requests.get",
            lambda *args, **kwargs: _FakeResponse(404, text="Not Found"),
        )
        try:
            fetch_html("https://example.test/listing")
            pytest.fail("Expected PermanentHTTPError to be raised")
        except PermanentHTTPError:
            pass

"""Unit tests for job_market_intel.scrapers.indeed.client.IndeedClient.

Deliberately does not open a real browser (seleniumbase is only installed
via the optional `selenium` extra, and a real Chromium session has no
place in a fast unit-test suite anyway). Instead:
    - detect_challenge() is a pure static method, tested directly against
      known-good/known-bad page text.
    - Everything that needs a driver has one injected via
      IndeedClient._driver (a MagicMock standing in for seleniumbase's
      driver object) so the client's own guard-rail and bookkeeping logic
      (raising IndeedFetchError before a session is open, counting
      pages/details visited) is verified without a real browser.

Pacing delays (time.sleep) are patched out everywhere so this suite stays
fast — asserting the *configured* delay window happened is left to a
manual/live run, not something worth slowing down `pytest` for.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from job_market_intel.scrapers.indeed.client import IndeedClient
from job_market_intel.scrapers.indeed.config import IndeedSettings
from job_market_intel.scrapers.indeed.exceptions import IndeedFetchError


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("job_market_intel.scrapers.indeed.client.time.sleep", lambda _: None)


@pytest.fixture
def client_with_mock_driver() -> IndeedClient:
    client = IndeedClient(settings=IndeedSettings())
    client._driver = MagicMock()  # noqa: SLF001 - deliberate test injection, see module docstring
    client._driver.page_source = "<html>ok</html>"
    return client


class TestDetectChallenge:
    @pytest.mark.parametrize(
        "page_source",
        [
            "<html>Additional Verification Required</html>",
            "<html>Please Verify You Are A Human before continuing</html>",
            "<html>We detected unusual traffic from your network</html>",
        ],
    )
    def test_challenge_markers_detected(self, page_source: str) -> None:
        assert IndeedClient.detect_challenge(page_source) is True

    def test_ordinary_page_not_flagged(self) -> None:
        html = "<html><body><div class='job_seen_beacon'>Software Engineer</div></body></html>"
        assert IndeedClient.detect_challenge(html) is False


class TestSessionGuardRails:
    def test_open_search_before_open_session_raises(self) -> None:
        client = IndeedClient(settings=IndeedSettings())
        with pytest.raises(IndeedFetchError):
            client.open_search("engineer", "Remote")

    def test_go_to_next_search_page_before_open_session_raises(self) -> None:
        client = IndeedClient(settings=IndeedSettings())
        with pytest.raises(IndeedFetchError):
            client.go_to_next_search_page()

    def test_open_detail_in_new_tab_before_open_session_raises(self) -> None:
        client = IndeedClient(settings=IndeedSettings())
        with pytest.raises(IndeedFetchError):
            client.open_detail_in_new_tab("https://www.indeed.com/viewjob?jk=abc")


class TestPageCounters:
    def test_open_search_increments_search_pages_visited(
        self, client_with_mock_driver: IndeedClient
    ) -> None:
        assert client_with_mock_driver.search_pages_visited == 0
        client_with_mock_driver.open_search("engineer", "Remote")
        assert client_with_mock_driver.search_pages_visited == 1

    def test_go_to_next_search_page_returns_none_when_no_next_link(
        self, client_with_mock_driver: IndeedClient
    ) -> None:
        client_with_mock_driver._driver.find_elements.return_value = []  # noqa: SLF001
        result = client_with_mock_driver.go_to_next_search_page()
        assert result is None
        assert client_with_mock_driver.search_pages_visited == 0

    def test_go_to_next_search_page_clicks_and_increments(
        self, client_with_mock_driver: IndeedClient
    ) -> None:
        next_link = MagicMock()
        client_with_mock_driver._driver.find_elements.return_value = [next_link]  # noqa: SLF001
        result = client_with_mock_driver.go_to_next_search_page()
        next_link.click.assert_called_once()
        assert result == "<html>ok</html>"
        assert client_with_mock_driver.search_pages_visited == 1

    def test_driver_error_on_open_search_raises_fetch_error(
        self, client_with_mock_driver: IndeedClient
    ) -> None:
        client_with_mock_driver._driver.get.side_effect = RuntimeError("boom")  # noqa: SLF001
        with pytest.raises(IndeedFetchError):
            client_with_mock_driver.open_search("engineer", "Remote")


class TestCloseSession:
    def test_close_session_is_safe_when_never_opened(self) -> None:
        client = IndeedClient(settings=IndeedSettings())
        client.close_session()  # must not raise

    def test_close_session_swallows_quit_errors(
        self, client_with_mock_driver: IndeedClient
    ) -> None:
        client_with_mock_driver._driver.quit.side_effect = RuntimeError("already dead")  # noqa: SLF001
        client_with_mock_driver.close_session()  # must not raise


class TestOpenSession:
    def test_open_session_uses_uc_subprocess_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_driver_instance = MagicMock()
        mock_driver_ctor = MagicMock(return_value=mock_driver_instance)
        fake_seleniumbase = types.SimpleNamespace(Driver=mock_driver_ctor)

        monkeypatch.setitem(sys.modules, "seleniumbase", fake_seleniumbase)

        client = IndeedClient(settings=IndeedSettings())
        client.open_session()

        mock_driver_ctor.assert_called_once()
        assert mock_driver_ctor.call_args.kwargs["uc"] is True
        mock_driver_instance.set_page_load_timeout.assert_called_once_with(
            client._settings.page_load_timeout_seconds  # noqa: SLF001 - deliberate assertion on config wiring
        )

    def test_open_session_plain_driver_when_uc_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_driver_instance = MagicMock()
        mock_driver_ctor = MagicMock(return_value=mock_driver_instance)
        fake_seleniumbase = types.SimpleNamespace(Driver=mock_driver_ctor)

        monkeypatch.setitem(sys.modules, "seleniumbase", fake_seleniumbase)

        mock_options = MagicMock()
        mock_service = MagicMock()
        mock_webdriver = types.SimpleNamespace(
            Chrome=MagicMock(return_value=mock_driver_instance),
            ChromeOptions=MagicMock(return_value=mock_options),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(webdriver=mock_webdriver),
        )
        fake_service_mod = types.SimpleNamespace(Service=MagicMock(return_value=mock_service))
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            fake_service_mod,
        )
        # `from selenium.webdriver.chrome.service import Service` must resolve
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            fake_service_mod,
        )

        client = IndeedClient(settings=IndeedSettings(headless=True, uc_enabled=False))
        client.open_session()

        mock_driver_instance.set_page_load_timeout.assert_called_once_with(
            client._settings.page_load_timeout_seconds  # noqa: SLF001
        )

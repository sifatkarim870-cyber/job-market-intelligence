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
import time
import types
from unittest.mock import MagicMock

import pytest

from job_market_intel.scrapers.indeed.client import _PLAIN_CHROME_ARGS, IndeedClient
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

    def test_open_session_plain_driver_gets_a_generous_handshake_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slow machine's session start must not die on selenium's own 120s
        driver read timeout.

        The mechanism matters here: an earlier version raised
        socket.getdefaulttimeout() instead, which does nothing at all, because
        ChromiumRemoteConnection passes an explicit timeout=120 when it builds
        its own ClientConfig. That version still failed at exactly
        "read timeout=120" with INDEED_SESSION_START_TIMEOUT_SECONDS=300 set.
        """
        mock_driver_instance = MagicMock()
        observed_timeouts: list[float | None] = []
        monkeypatch.setitem(sys.modules, "seleniumbase", types.SimpleNamespace(Driver=MagicMock()))

        # Stand in for the connection class selenium instantiates internally,
        # recording the ClientConfig timeout it is handed. client.py patches
        # the real class on the real chromium webdriver module (that's the
        # only place webdriver.Chrome() looks it up), so these tests patch the
        # real module attributes rather than replacing sys.modules entries.
        from selenium.webdriver.chromium import webdriver as chromium_webdriver

        class FakeConnection:
            def __init__(
                self, *args: object, client_config: object = None, **kwargs: object
            ) -> None:
                observed_timeouts.append(getattr(client_config, "timeout", None))

        original_connection = chromium_webdriver.ChromiumRemoteConnection
        monkeypatch.setattr(chromium_webdriver, "ChromiumRemoteConnection", FakeConnection)

        def fake_chrome(**_: object) -> MagicMock:
            # Mirrors what webdriver.Chrome() does internally: instantiate
            # whatever connection class the module currently holds.
            chromium_webdriver.ChromiumRemoteConnection(
                remote_server_addr="http://localhost:1234",
                vendor_prefix="goog",
                browser_name="chrome",
                keep_alive=True,
            )
            return mock_driver_instance

        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(
                webdriver=types.SimpleNamespace(
                    Chrome=MagicMock(side_effect=fake_chrome),
                    ChromeOptions=MagicMock(return_value=MagicMock()),
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            types.SimpleNamespace(Service=MagicMock(return_value=MagicMock())),
        )

        settings = IndeedSettings(
            headless=True, uc_enabled=False, session_start_timeout_seconds=777.0
        )
        IndeedClient(settings=settings).open_session()

        # The whole point: the handshake ran under 777s, not selenium's 120s.
        assert observed_timeouts == [777.0]
        # Whatever was in place when open_session() ran is back afterwards, so
        # the override can't leak into a later session in the same process.
        # (FakeConnection here stands in for "what was there before".)
        assert chromium_webdriver.ChromiumRemoteConnection is FakeConnection
        assert original_connection.__name__ == "ChromiumRemoteConnection"

    def test_plain_driver_timeout_override_survives_a_failed_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The restore is in a finally: a failed handshake must not leave the
        process-wide swap in place for the next attempt.
        """
        from selenium.webdriver.chromium import webdriver as chromium_webdriver

        class FakeConnection:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.client_config = object()

        monkeypatch.setattr(chromium_webdriver, "ChromiumRemoteConnection", FakeConnection)
        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(
                webdriver=types.SimpleNamespace(
                    Chrome=MagicMock(side_effect=RuntimeError("no chrome here")),
                    ChromeOptions=MagicMock(return_value=MagicMock()),
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            types.SimpleNamespace(Service=MagicMock(return_value=MagicMock())),
        )

        client = IndeedClient(settings=IndeedSettings(headless=True, uc_enabled=False))
        with pytest.raises(IndeedFetchError, match="no chrome here"):
            client.open_session()

        assert chromium_webdriver.ChromiumRemoteConnection is FakeConnection

    def test_plain_driver_timeout_override_is_not_left_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The swap only lasts for the handshake — a process-wide patch left in
        place would silently give every later driver call a 5-minute deadline.
        """
        monkeypatch.setitem(sys.modules, "seleniumbase", types.SimpleNamespace(Driver=MagicMock()))

        sentinel = object()

        class FakeConnection:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.client_config = sentinel  # no real timeout to reset

        from selenium.webdriver.chromium import webdriver as chromium_webdriver

        monkeypatch.setattr(chromium_webdriver, "ChromiumRemoteConnection", FakeConnection)
        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(
                webdriver=types.SimpleNamespace(
                    Chrome=MagicMock(return_value=MagicMock()),
                    ChromeOptions=MagicMock(return_value=MagicMock()),
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            types.SimpleNamespace(Service=MagicMock(return_value=MagicMock())),
        )

        IndeedClient(settings=IndeedSettings(headless=True, uc_enabled=False)).open_session()

        assert chromium_webdriver.ChromiumRemoteConnection is FakeConnection
        assert isinstance(
            chromium_webdriver.ChromiumRemoteConnection,
            type,
        )  # not left as an instance or a bare function

    def test_plain_chrome_args_omit_the_two_flags_that_break_the_ci_runner(
        self,
    ) -> None:
        """Regression guard for a measured failure, not a preference.

        On the 837MiB CI runner, --disable-gpu made Chrome stand up a GPU
        process it doesn't need and the session never started (127s
        timeout), and --disable-dev-shm-usage pushed shared memory to disk
        for no benefit since /dev/shm there is 419MiB. Both were in the
        flag list for a long time on the assumption that they were
        obviously right for a small VM. See _PLAIN_CHROME_ARGS's comment for
        the full set of measurements.
        """
        assert "--disable-gpu" not in _PLAIN_CHROME_ARGS
        assert "--disable-dev-shm-usage" not in _PLAIN_CHROME_ARGS
        # --no-sandbox is the opposite case: still required there.
        assert "--no-sandbox" in _PLAIN_CHROME_ARGS

    def test_open_session_retries_a_launch_that_fails_on_available_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed launch is retried before the row is written off.

        On the CI runner the identical Chrome flag set failed at 127s in one
        run and started in 49s in another, with available memory swinging
        279MiB -> 378MiB between them. That is a coin flip, not a bug, so a
        second attempt is the right response and writing the queue row off
        after one is not.
        """
        monkeypatch.setitem(sys.modules, "seleniumbase", types.SimpleNamespace(Driver=MagicMock()))
        monkeypatch.setattr(time, "sleep", lambda _: None)

        attempts = 0

        def flaky_chrome(**_: object) -> MagicMock:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("DevToolsActivePort file doesn't exist")
            return MagicMock()

        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(
                webdriver=types.SimpleNamespace(
                    Chrome=MagicMock(side_effect=flaky_chrome),
                    ChromeOptions=MagicMock(return_value=MagicMock()),
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            types.SimpleNamespace(Service=MagicMock(return_value=MagicMock())),
        )

        settings = IndeedSettings(
            headless=True,
            uc_enabled=False,
            session_start_attempts=3,
            session_start_retry_wait_seconds=0.0,
        )
        client = IndeedClient(settings=settings)
        client.open_session()

        assert attempts == 3
        assert client._driver is not None  # noqa: SLF001 - the point of the test

    def test_open_session_gives_up_after_the_configured_number_of_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "seleniumbase", types.SimpleNamespace(Driver=MagicMock()))
        monkeypatch.setattr(time, "sleep", lambda _: None)

        attempts = 0

        def always_fails(**_: object) -> None:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("DevToolsActivePort file doesn't exist")

        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(
                webdriver=types.SimpleNamespace(
                    Chrome=MagicMock(side_effect=always_fails),
                    ChromeOptions=MagicMock(return_value=MagicMock()),
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            types.SimpleNamespace(Service=MagicMock(return_value=MagicMock())),
        )

        settings = IndeedSettings(
            headless=True,
            uc_enabled=False,
            session_start_attempts=2,
            session_start_retry_wait_seconds=0.0,
        )
        with pytest.raises(IndeedFetchError, match="2 attempts"):
            IndeedClient(settings=settings).open_session()

        assert attempts == 2

    def test_open_session_plain_driver_raises_indeed_fetch_error_when_it_will_not_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "seleniumbase", types.SimpleNamespace(Driver=MagicMock()))
        monkeypatch.setitem(
            sys.modules,
            "selenium",
            types.SimpleNamespace(
                webdriver=types.SimpleNamespace(
                    Chrome=MagicMock(side_effect=RuntimeError("chrome is not coming up")),
                    ChromeOptions=MagicMock(return_value=MagicMock()),
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "selenium.webdriver.chrome.service",
            types.SimpleNamespace(Service=MagicMock(return_value=MagicMock())),
        )

        client = IndeedClient(settings=IndeedSettings(headless=True, uc_enabled=False))
        with pytest.raises(IndeedFetchError, match="chrome is not coming up"):
            client.open_session()

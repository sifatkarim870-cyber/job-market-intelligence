"""Selenium browser client for Indeed.

This is the one piece of the six-file scraper shape that has no real
precedent in remoteok/remotive/weworkremotely's client.py — those wrap
``common/http_client.py``'s plain HTTP fetch_json/fetch_html through
``common/retry.py``. There is nothing to reuse from that for a stateful
browser session, so this file doesn't try to force a fit; it follows the
*shape* (a client class the pipeline calls into, that raises the module's
own exceptions and knows nothing about parsing or persistence) without
pretending the implementation is shared.

Library choice: seleniumbase in UC ("undetected chrome") mode, not the bare
``selenium`` package. Confirmed decision from scoping this scraper — plain
Selenium's default WebDriver protocol is fingerprinted and commonly blocked
on Indeed regardless of request pacing; seleniumbase patches those markers
while exposing a Selenium-compatible driver underneath, and is actively
maintained against an anti-bot landscape that will keep changing over a
years-long crawl.

Pacing model, confirmed from scoping:
    - A randomized delay (config.page_action_min/max_wait_seconds) before
      every navigation or click — never a fixed sleep.
    - A longer randomized pause every ``config.long_pause_every_n_pages``
      search-result pages.
    - Hard per-session caps on search pages and detail pages
      (config.max_search_pages_per_session /
      config.max_detail_pages_per_session) — the pipeline is responsible
      for stopping at those caps and leaving the rest of a query for the
      next run via ops.scrape_query_queue; this client just does what it's
      told.

Blocking: never solved, never routed around. detect_challenge() looks for
the page being a CAPTCHA/human-verification challenge rather than the
search or detail page it was asked to load, and the pipeline treats a
positive detection as an immediate, clean stop (IndeedBlockedError) — see
exceptions.py and pipeline.py.
"""

from __future__ import annotations

import logging
import random
import socket
import time
from typing import Any
from urllib.parse import quote_plus

from job_market_intel.scrapers.indeed.config import IndeedSettings
from job_market_intel.scrapers.indeed.exceptions import IndeedFetchError

logger = logging.getLogger(__name__)

# Substrings that show up on Indeed's own challenge/verification interstitial
# rather than on a real search or job page. Matched case-insensitively
# against page text. Deliberately checked against visible text, not just the
# URL, since the URL alone (e.g. a redirect through /err) isn't a reliable
# signal on its own.
_CHALLENGE_MARKERS = (
    "additional verification required",
    "verify you are a human",
    "unusual traffic",
    "please verify you are a human",
    "checking your browser",
)

_NEXT_PAGE_SELECTOR = 'a[aria-label="Next Page"], a[data-testid="pagination-page-next"]'

# Chrome flags used by the UC-off path (see open_session). Measured on the
# self-hosted CI runner (an 837MiB, 0-swap Azure VM with a 419MiB /dev/shm)
# rather than guessed — see .github/workflows/indeed_uc_probe.yml, which
# tries each of these sets in its own process:
#
#     --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage
#         -> FAILED, 127s, ReadTimeoutError from the driver
#     --headless=new --no-sandbox --disable-dev-shm-usage            -> 69s
#     --headless=new --no-sandbox                                    -> 49s  <- this set
#     ... + --renderer-process-limit=1                               -> 63s
#     ... + --single-process                                          -> died, 22s
#     --headless=old --no-sandbox --disable-gpu --disable-dev-shm-usage -> 81s
#
# So two of the three flags that looked obviously right for a small VM were
# the problem, and for opposite reasons:
#
#   --disable-gpu: on a VM with no GPU this still stands up Chrome's GPU
#     process rather than skipping it, and the extra process is what pushes
#     the browser past this VM's memory budget. Dropping it was the single
#     change between the 127s timeout and a session.
#   --disable-dev-shm-usage: /dev/shm here is 419MiB, comfortably enough,
#     so the flag only forces Chrome's shared memory out to disk in /tmp.
#     Slower, and it was the second-worst set measured.
#
# The remaining flags silence Chrome's own first-run/background network
# chatter (DBus lookups, GCM registration, component-update checks), which
# the driver log showed eating a cold start on this machine. They don't fix
# anything on their own — startup is still ~49s, which is why
# session_start_timeout_seconds exists — but they shave it and cost nothing.
#
# Deliberately *not* here: anything that only exists to make the browser
# look less like automation. These are about getting a browser started on a
# constrained machine; the anti-fingerprinting job belongs to UC mode, which
# is the default (see IndeedSettings.uc_enabled).
_PLAIN_CHROME_ARGS = (
    "--no-sandbox",
    "--window-size=1920,1080",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-client-side-phishing-detection",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-breakpad",
    "--disable-popup-blocking",
    "--disable-search-engine-choice-screen",
    "--metrics-recording-only",
    "--password-store=basic",
    "--use-mock-keychain",
    "--disable-features="
    "Translate,OptimizationHints,MediaRouter,InterestFeedContentSuggestions,CalculateNativeWinOcclusion",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
)

# Where the UC-off path points chromedriver's own stderr. On CI this is the
# single most useful thing to have when a session fails to start, so it goes
# to a file the workflow can cat rather than into the scraper's own log.
_CHROMEDRIVER_LOG_PATH = "/tmp/chromedriver.log"

# Selenium's built-in HTTP read timeout for driver calls, and what open_session
# puts back once the session is up (see the socket.setdefaulttimeout dance
# there — the long handshake timeout is only wanted for the handshake).
_SELENIUM_DEFAULT_DRIVER_TIMEOUT = 120.0


class IndeedClient:
    """Owns one browser session's lifecycle: open, navigate, paginate,
    visit detail pages in a side tab, detect a block, close.

    Deliberately stateful (unlike the other three scrapers' stateless
    fetch_json/fetch_html functions) because a real browser session *is*
    state — that's the whole reason Selenium is being used here instead of
    a plain HTTP client.
    """

    def __init__(self, settings: IndeedSettings) -> None:
        self._settings = settings
        # Typed Any, not a seleniumbase type: seleniumbase is only ever
        # imported lazily inside open_session() (see that method's own
        # docstring for why), so no stub-backed type is available at
        # module scope to annotate this with, and stubbing it out would
        # require a hard import this module deliberately avoids.
        self._driver: Any = None
        self._search_pages_visited = 0
        self._detail_pages_visited = 0

    # -- session lifecycle ----------------------------------------------

    def open_session(self) -> None:
        """Start a fresh browser session. Must be paired with close_session()
        in a try/finally at the call site (see pipeline.py) — a session left
        open on an unhandled exception is exactly the kind of orphaned
        process that turns a years-long scheduled job into a slow resource
        leak.
        """
        # Imported here, not at module level: seleniumbase is only needed
        # when a real session is actually opened, which keeps it out of the
        # import path for anything that just needs config/models/exceptions
        # (e.g. unit tests that never touch a real browser).
        from seleniumbase import Driver

        logger.info("indeed.session.open headless=%s", self._settings.headless)
        if self._settings.uc_enabled:
            # Default: undetected-Chrome mode, the non-fingerprinted way
            # to talk to Indeed, confirmed on local machines / dedicated
            # host with a real display.
            self._driver = Driver(
                uc=True,
                headless2=self._settings.headless,
                agent=self._settings.request_user_agent,
                page_load_strategy="eager",
            )
        else:
            # UC-off path only exercised on the self-hosted CI runner,
            # where any seleniumbase Driver variant hung sessions. Plain
            # selenium's own webdriver.Chrome works on the same VM.
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service

            options = webdriver.ChromeOptions()
            if self._settings.headless:
                # headless=new (the modern headless, not the removed old
                # one) is the only Chrome mode that starts reliably on that
                # VM -- the Xvfb-backed alternative never came up there.
                options.add_argument("--headless=new")
            for arg in _PLAIN_CHROME_ARGS:
                options.add_argument(arg)
            options.add_argument(f"--user-agent={self._settings.request_user_agent}")
            service = Service(log_output=_CHROMEDRIVER_LOG_PATH)
            self._driver = self._start_plain_chrome(options, service)
        self._driver.set_page_load_timeout(self._settings.page_load_timeout_seconds)
        self._search_pages_visited = 0
        self._detail_pages_visited = 0

    def _start_plain_chrome(self, options: Any, service: Any) -> Any:
        """Builds the non-UC Chrome session, with two concessions to slow
        machines that are otherwise easy to mistake for a scraper bug.

        First, selenium gives every driver HTTP call a 120s read timeout,
        and a cold Chrome on a low-memory machine can spend longer than
        that just launching before it can answer the very first request --
        on the CI runner it was ~45s when it worked and unbounded when it
        didn't, so the honest failure was an opaque urllib3 ReadTimeoutError
        from inside selenium rather than anything actionable. selenium has no
        public knob for that timeout (ChromiumDriver constructs its own
        ClientConfig, whose timeout defaults to socket.getdefaulttimeout()),
        so the default socket timeout is raised for the duration of the
        constructor call and restored immediately after. Only the handshake
        gets the generous budget: the driver's read timeout is put back to
        selenium's default once there's a session, since
        set_page_load_timeout() bounds actual page loads from that point on
        and leaving it large would just make a dead driver hang for minutes.

        Second, a driver that never starts is reported as IndeedFetchError
        with how long it took, so the pipeline can record it as a controlled
        failure for this queue row instead of the whole run dying on a
        traceback -- see pipeline._run_browser_phase().
        """
        from selenium import webdriver

        started = time.monotonic()
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self._settings.session_start_timeout_seconds)
        try:
            driver = webdriver.Chrome(options=options, service=service)
        except Exception as exc:
            raise IndeedFetchError(
                f"chrome session failed to start after {time.monotonic() - started:.0f}s: {exc}"
            ) from exc
        finally:
            socket.setdefaulttimeout(previous_timeout)

        elapsed = time.monotonic() - started
        logger.info("indeed.session.plain_chrome_started elapsed=%.1fs", elapsed)
        if elapsed > 60:
            # Worth saying out loud: this is the signal that a machine is
            # too slow/too small for the flags above to have helped, and the
            # number to compare against when that changes.
            logger.warning("indeed.session.slow_start elapsed=%.1fs", elapsed)

        executor = getattr(driver, "command_executor", None)
        client_config = getattr(executor, "client_config", None)
        if client_config is not None:
            client_config.timeout = _SELENIUM_DEFAULT_DRIVER_TIMEOUT
        return driver

    def close_session(self) -> None:
        if self._driver is not None:
            logger.info(
                "indeed.session.close search_pages=%d detail_pages=%d",
                self._search_pages_visited,
                self._detail_pages_visited,
            )
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001 - closing a possibly-already-dead
                # driver must never mask the real error that caused the
                # session to end; log and move on.
                logger.warning("indeed.session.close_failed", exc_info=True)
            finally:
                self._driver = None

    @property
    def search_pages_visited(self) -> int:
        return self._search_pages_visited

    @property
    def detail_pages_visited(self) -> int:
        return self._detail_pages_visited

    # -- pacing -----------------------------------------------------------

    def _wait_between_actions(self) -> None:
        delay = random.uniform(
            self._settings.page_action_min_wait_seconds,
            self._settings.page_action_max_wait_seconds,
        )
        time.sleep(delay)

    def _maybe_long_pause(self) -> None:
        if (
            self._search_pages_visited > 0
            and self._search_pages_visited % self._settings.long_pause_every_n_pages == 0
        ):
            pause = random.uniform(
                self._settings.long_pause_min_seconds,
                self._settings.long_pause_max_seconds,
            )
            logger.info("indeed.session.long_pause seconds=%.1f", pause)
            time.sleep(pause)

    # -- navigation ---------------------------------------------------

    def open_search(self, query: str, location: str) -> str:
        """Navigate to page 1 of a search and return the rendered page
        source. Raises IndeedFetchError on a driver-level failure (timeout,
        crashed session) — a *successful* load that turns out to be a
        challenge page is not this client's call to make; that's
        detect_challenge()'s job, checked by the pipeline after this
        returns.
        """
        if self._driver is None:
            raise IndeedFetchError("open_search called before open_session")
        url = f"{self._settings.base_url}/jobs?q={quote_plus(query)}&l={quote_plus(location)}"
        try:
            self._wait_between_actions()
            self._driver.get(url)
        except Exception as exc:  # noqa: BLE001 - any driver failure here is
            # a fetch failure from the pipeline's point of view, regardless
            # of Selenium's specific exception hierarchy.
            raise IndeedFetchError(f"failed to load search page: {url}") from exc
        self._search_pages_visited += 1
        self._maybe_long_pause()
        return self._driver.page_source

    def go_to_next_search_page(self) -> str | None:
        """Click the rendered "next page" control and return the new page's
        source, or None if there is no next page (end of results for this
        query/location). Confirmed decision: never construct a ?start=N
        URL by hand — Indeed's canonical pagination URL slug isn't
        something to guess at, and clicking the control a browser session
        actually sees is the more realistic behavior anyway.
        """
        if self._driver is None:
            raise IndeedFetchError("go_to_next_search_page called before open_session")
        try:
            next_links = self._driver.find_elements("css selector", _NEXT_PAGE_SELECTOR)
            if not next_links:
                return None
            self._wait_between_actions()
            next_links[0].click()
        except Exception as exc:  # noqa: BLE001
            raise IndeedFetchError("failed to click next-page control") from exc
        self._search_pages_visited += 1
        self._maybe_long_pause()
        return self._driver.page_source

    def open_detail_in_new_tab(self, detail_url: str) -> str:
        """Open a job's detail page in a new tab, capture its source, and
        close the tab — leaving the search-results tab (and its pagination
        state) untouched. This is why detail pages don't just call
        driver.get() directly: doing that on the main tab would lose the
        current search page's position.
        """
        if self._driver is None:
            raise IndeedFetchError("open_detail_in_new_tab called before open_session")
        original_handle = self._driver.current_window_handle
        try:
            self._wait_between_actions()
            self._driver.execute_script("window.open(arguments[0], '_blank');", detail_url)
            self._driver.switch_to.window(self._driver.window_handles[-1])
            source = self._driver.page_source
        except Exception as exc:  # noqa: BLE001
            raise IndeedFetchError(f"failed to load detail page: {detail_url}") from exc
        finally:
            if self._driver.current_window_handle != original_handle:
                self._driver.close()
            self._driver.switch_to.window(original_handle)
        self._detail_pages_visited += 1
        return source

    @staticmethod
    def detect_challenge(page_source: str) -> bool:
        """True if the given page source looks like Indeed's own CAPTCHA/
        human-verification interstitial rather than real content. Checked
        by the pipeline after every navigation; a positive result raises
        IndeedBlockedError and ends the session — this function itself
        never raises, never retries, never attempts to solve anything.
        """
        lowered = page_source.lower()
        return any(marker in lowered for marker in _CHALLENGE_MARKERS)

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

            options = webdriver.ChromeOptions()
            for arg in (
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ):
                options.add_argument(arg)
            self._driver = webdriver.Chrome(options=options)
        self._driver.set_page_load_timeout(self._settings.page_load_timeout_seconds)
        self._search_pages_visited = 0
        self._detail_pages_visited = 0

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

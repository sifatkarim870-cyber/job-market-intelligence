"""Fetches raw postings by rendering pages in a real Chrome.

The HTML framework uses ``requests`` and reads the document the server sends.
Boards that render their listings client-side send an empty shell to that, and
the shell is what a "no job links" verdict was really measuring. This client
drives a Chrome (through seleniumbase, in undetected-Chrome mode) and reads
``driver.page_source`` *after* the page has run its JavaScript.

Everything downstream -- the parser, the quality gate, the validator, the
cleaner, persistence -- is the HTML framework's code. This client only has to
produce the same record shape, so the two frameworks cannot drift apart.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.html_scraper.client import (
    _extract_links_from_html,
    _is_offsite_social,
    _json_ld_job_posting,
    mapped_json_html,
)
from job_market_intel.validation.html_scraper_quality import (
    SECTION_FRAGMENTS,
    SECTION_SEGMENTS,
    has_job_keyword,
)

from .config import BrowserScraperSettings, BrowserSiteConfig, load_browser_site_config
from .exceptions import BrowserChallengeError, BrowserFetchError

#: Markers that mean "you were served a challenge, not the board". Never solved.
#:
#: Two lists, because they are checked against different things. The text
#: markers are matched against the *visible* text of the rendered page: a page
#: that merely links a reCAPTCHA script contains the word "captcha" in its
#: markup while being a perfectly good job list, and matching the raw HTML
#: rejected a source that worked. The HTML markers are structural and only
#: appear on an actual challenge page.
DEFAULT_CHALLENGE_TEXT_MARKERS: tuple[str, ...] = (
    "just a moment",
    "checking your browser",
    "pardon our interruption",
    "enable javascript and cookies to continue",
    "verify you are human",
    "verify that you are human",
    "unusual traffic",
    "attention required",
    "access denied",
    "request unsuccessful. incapsula",
    "captcha",
    "安全验证",
    "请输入验证码",
)

DEFAULT_CHALLENGE_HTML_MARKERS: tuple[str, ...] = (
    "cf-browser-verification",
    "cf-challenge",
    "challenge-platform",
    "px-captcha",
    "perimeterx",
    "captcha-container",
    "g-recaptcha",
    "hcaptcha",
)


def _is_dead_session(exc: Exception) -> bool:
    """True when the exception means the browser is gone, not that the page failed.

    Selenium raises different classes for the same event depending on where it
    noticed: NoSuchWindowException, TargetClosedError, InvalidSessionIdException.
    Matching on the class name keeps this module free of a selenium import at
    module scope, which is what lets the unit tests import it without a browser.
    """
    name = type(exc).__name__
    if name in {
        "NoSuchWindowException",
        "TargetClosedError",
        "InvalidSessionIdException",
        "WebDriverException",
    }:
        return True
    message = str(exc)
    return "target window already closed" in message or "no such window" in message


def _challenge_markers(config: BrowserSiteConfig) -> tuple[str, ...]:
    extra = tuple(
        marker.strip().lower()
        for marker in (config.challenge_markers or "").split(",")
        if marker.strip()
    )
    return DEFAULT_CHALLENGE_TEXT_MARKERS + extra


def _ignored_markers(config: BrowserSiteConfig) -> frozenset[str]:
    """Markers this site has explicitly declared inert (comma separated).

    A board can embed a passive CAPTCHA widget -- MojeDelo renders the
    reCAPTCHA badge on every ad -- and still serve ordinary content. Naming
    the marker here keeps the built-in list honest for every other site while
    letting that one board through. Only the named markers are skipped.
    """
    return frozenset(
        marker.strip().lower()
        for marker in (config.ignore_challenge_markers or "").split(",")
        if marker.strip()
    )


def _error_markers(config: BrowserSiteConfig) -> tuple[str, ...]:
    """Markers that mean "the origin answered with an error page" (comma separated).

    A hit is a per-ad fetch failure, not a bot challenge: the origin (or the
    CDN in front of it) is briefly unhealthy and will likely serve the next ad
    normally. Kept separate from :attr:`_challenge_markers` because the two
    call for opposite behaviour -- skip this ad and continue versus stop the
    run -- and because these strings ("gateway time-out") are ordinary English
    that only an errored page, never a posting, contains in bulk.
    """
    return tuple(
        marker.strip().lower()
        for marker in (config.error_markers or "").split(",")
        if marker.strip()
    )


def _visible_text(html: str) -> str:
    """The text a person would see, with scripts and styles removed."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True).lower()


def _clean_detail_url(link: str, strip_query: bool) -> str:
    """A discovered detail URL, optionally trimmed to its bare path.

    A board can publish its ad links with tracking parameters that its own
    robots.txt forbids for a generic crawler while the clean path is allowed:
    jobstreet.com.ph/.sg disallow ``*/job/*?*type=`` and ``*?`` but allow
    ``/job/<id>``. With ``strip_query`` the query string and fragment are
    removed so the fetch targets the path robots.txt allows. Off on every source
    that does not opt in, which keeps the exact href the page linked.
    """
    if not strip_query:
        return link
    return link.split("#", 1)[0].split("?", 1)[0]


def _looks_rendered(html: str) -> bool:
    """Whether a page has the shape of a rendered posting page.

    A client-side shell answers with the navigation and little else; a
    rendered posting page has a heading and a body of text. Both conditions
    matter: a page can have an ``h1`` and still be the shell, and it can have
    plenty of text and still be a challenge page (which is caught separately).
    """
    if len(html) < 5000:
        return False
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("h1") is None:
        return False
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return len(soup.get_text(" ", strip=True)) > 300


class BrowserScraperClient:
    """Renders listing and detail pages and returns raw HTML records."""

    def __init__(
        self,
        source_code: str,
        settings: BrowserScraperSettings | None = None,
        site_config: BrowserSiteConfig | None = None,
    ) -> None:
        self._settings = settings or BrowserScraperSettings()
        self._site_config = site_config or load_browser_site_config(
            source_code, self._settings.sites_dir
        )
        self._driver: Any = None
        self._detail_pages_visited = 0

    # -- session lifecycle ----------------------------------------------

    def open_session(self) -> None:
        """Start Chrome. Must be paired with close_session()."""
        proxy = os.environ.get("BROWSER_SCRAPER_PROXY", "").strip()
        if self._site_config.uc_mode:
            from seleniumbase import Driver

            kwargs: dict[str, Any] = {
                "uc": True,
                "headless2": self._site_config.headless,
                "page_load_strategy": "eager",
            }
            if proxy:
                kwargs["proxy"] = proxy
            self._driver = Driver(**kwargs)
        else:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service

            options = webdriver.ChromeOptions()
            if self._site_config.headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--user-agent=job-market-intel-research (research@example.org)")
            if proxy:
                options.add_argument(f"--proxy-server={proxy}")
            for extra in (self._site_config.chrome_args or "").split():
                options.add_argument(extra)
            self._driver = webdriver.Chrome(options=options, service=Service())

        self._driver.set_page_load_timeout(60)
        self._detail_pages_visited = 0
        logger.info(
            "browser_scraper session open for {} (uc={}, headless={}, proxy={})",
            self._site_config.source_code,
            self._site_config.uc_mode,
            self._site_config.headless,
            proxy or "none",
        )

    def close_session(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001 - closing a dead driver must not
                # mask the error that ended the run.
                logger.warning("browser_scraper session close failed", exc_info=True)
            finally:
                self._driver = None

    # -- navigation -----------------------------------------------------

    def listing_url(self, page: int = 1) -> str:
        """URL of a listing page. Page 1 uses the bare listing path.

        Same rule as the HTML client: the pagination string is *appended* to
        the listing path, so a config with ``/jobs`` and ``?page={page}`` asks
        for ``/jobs?page=2`` and not ``/?page=2``.
        """
        return self._listing_url_for(self._site_config.listing_path, page)

    def _listing_url_for(self, listing_path: str, page: int = 1) -> str:
        """The URL of ``listing_path`` at ``page`` (page 1 is the bare path).

        A board whose pager counts its first page as zero (Wuzzuf's ``?start=``)
        names ``{zero_page}`` in ``listing_pagination``; the framework's 1-based
        ``page`` is shifted down by one. Page 1 still resolves to the bare path,
        which is that board's page 0, mirroring the HTML client's JSON-listing
        support for the same numbering.
        """
        base = f"{self._site_config.base_url.rstrip('/')}{listing_path}"
        if page <= 1:
            return base
        pagination = self._site_config.listing_pagination or ""
        if "{zero_page}" in pagination:
            return base + pagination.format(zero_page=page - 1)
        if "{page}" not in pagination:
            return base
        return base + pagination.format(page=page)

    def _navigate(self, url: str) -> None:
        """Load ``url`` in the current tab.

        A site behind a Cloudflare managed challenge can be given an opt-in
        reconnect window (``uc_reconnect_seconds``): SeleniumBase's
        ``uc_open_with_reconnect`` detaches from the tab, waits, and reattaches
        after the challenge has had time to solve -- the live CDP session during
        page load is itself a detection signal. Zero (the default) keeps the
        plain ``driver.get`` navigation every existing source relies on.
        """
        seconds = self._site_config.uc_reconnect_seconds
        if (
            self._site_config.uc_mode
            and seconds > 0
            and hasattr(self._driver, "uc_open_with_reconnect")
        ):
            self._driver.uc_open_with_reconnect(url, seconds)
        else:
            self._driver.get(url)

    def _render(self, url: str, ready_selector: str, wait_seconds: int) -> str:
        """Navigate, wait for the page to render, return its HTML."""
        if self._driver is None:
            raise BrowserFetchError("render called before the session was opened")
        try:
            self._navigate(url)
        except Exception as exc:  # noqa: BLE001 - any driver failure is a fetch
            # failure from the pipeline's point of view.
            raise BrowserFetchError(f"failed to load {url}: {exc}") from exc

        if ready_selector:
            try:
                self._driver.wait_for_element_present(ready_selector, timeout=wait_seconds)
            except Exception:  # noqa: BLE001 - a missing element is a fact
                # about the page, not a crash; the content check below decides.
                logger.info("browser_scraper: {} never showed {}", url, ready_selector)
        else:
            time.sleep(min(wait_seconds, 5))

        for _ in range(self._site_config.scroll_count):
            try:
                self._driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:  # noqa: BLE001
                break
            time.sleep(self._site_config.scroll_pause_seconds)

        self._click_load_more()

        return self._driver.page_source

    def _click_load_more(self) -> None:
        """Press the listing's "load more" control, if it declares one.

        A "load more" board renders one screenful and stops; the rest arrives
        only when the control is pressed, and each press appends another page
        (Töötukassa: 20 more ads per press). The press is done through
        ``arguments[0].click()`` rather than Selenium's ``click`` so an overlay
        or a cookie banner sitting on top of the button does not turn into a
        silently empty listing -- measured on 2026-10-28, where a plain click
        returned 20 links and the JavaScript click returned 40.
        """
        selector = self._site_config.listing_more_selector.strip()
        clicks = self._site_config.listing_more_clicks
        if not selector or clicks <= 0:
            return
        for attempt in range(1, clicks + 1):
            try:
                elements = self._driver.find_elements("css selector", selector)
            except Exception:  # noqa: BLE001 - a dead session is retried by the caller
                break
            if not elements:
                logger.info(
                    "browser_scraper: no '{}' after {} click(s); listing is as long as it gets",
                    selector,
                    attempt - 1,
                )
                break
            try:
                self._driver.execute_script("arguments[0].click();", elements[0])
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser_scraper: load-more click {} failed: {}", attempt, exc)
                break
            time.sleep(self._site_config.listing_more_pause_seconds)

    def _check_error_page(self, html: str, url: str) -> None:
        """Raise when the rendered page is an origin error page, not content.

        Cloudflare and friends answer with a 502/503/504 page that still has an
        ``h1`` and a few sentences of text, so ``_looks_rendered`` accepts it
        and the "job description" becomes "Gateway time-out". Callers treat
        this as a per-ad failure and keep going: the next ad usually loads.
        """
        markers = _error_markers(self._site_config)
        if not markers:
            return
        text = _visible_text(html[:200000])
        for marker in markers:
            if marker in text:
                raise BrowserFetchError(f"{url} returned an error page (matched {marker!r})")

    def _check_challenge(self, html: str, url: str) -> None:
        """Raise when the rendered page is a bot challenge rather than content."""
        ignored = _ignored_markers(self._site_config)
        lowered_html = html[:200000].lower()
        for marker in DEFAULT_CHALLENGE_HTML_MARKERS:
            if marker in ignored:
                continue
            if marker in lowered_html:
                raise BrowserChallengeError(f"{url} returned a bot challenge (matched {marker!r})")
        text = _visible_text(html[:200000])
        for marker in _challenge_markers(self._site_config):
            if marker in ignored:
                continue
            if marker in text:
                raise BrowserChallengeError(f"{url} returned a bot challenge (matched {marker!r})")

    # -- extraction -----------------------------------------------------

    def _links_on_page(self, html: str) -> list[dict[str, str]]:
        """Job links on a rendered listing page, by selector or auto-detection."""
        config = self._site_config
        jobs: list[dict[str, str]] = []

        selector = config.selectors.job_link
        if selector:
            soup = BeautifulSoup(html, "html.parser")
            for element in soup.select(selector):
                href = element.get("href")
                if not href:
                    continue
                link = _clean_detail_url(
                    urljoin(config.base_url, href.strip()),
                    config.detail_url_strip_query,
                )
                if _is_offsite_social(link):
                    continue
                jobs.append({"url": link, "title": element.get_text(" ", strip=True)})

        if not jobs:
            for url, text in _extract_links_from_html(html, config.base_url):
                url = _clean_detail_url(url, config.detail_url_strip_query)
                if not _is_offsite_social(url):
                    jobs.append({"url": url, "title": text})

        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for job in jobs:
            if job["url"] in seen:
                continue
            seen.add(job["url"])
            unique.append(job)
        return unique

    def discover_detail_paths(self, max_jobs: int | None = None) -> list[dict[str, str]]:
        """Walk the rendered listing pages and collect detail URLs.

        Every seed in :attr:`BrowserSiteConfig.listing_paths` is walked after
        ``listing_path``; when the pagination string carries no ``{page}`` there
        is only one page per seed, so the repeated-URL guard stops after page 1
        instead of re-rendering the same seed ``max_pages`` times.
        """
        found: list[dict[str, str]] = []
        seen: set[str] = set()
        budget = max_jobs or self._site_config.max_jobs_per_run
        challenge: str | None = None

        for seed in self._listing_seeds():
            served = self._discover_from_seed(seed, seen, found, budget)
            challenge = served or challenge
            if len(found) >= budget:
                break

        if challenge and not found:
            raise BrowserChallengeError(challenge)
        return found

    def _listing_seeds(self) -> list[str]:
        """:attr:`listing_path` first, then each extra path, de-duplicated."""
        seeds = [self._site_config.listing_path]
        for extra in self._site_config.listing_paths:
            extra = (extra or "").strip()
            if extra and extra not in seeds:
                seeds.append(extra)
        return seeds

    def _discover_from_seed(
        self,
        seed: str,
        seen: set[str],
        found: list[dict[str, str]],
        budget: int,
    ) -> str | None:
        """Walk one seed's rendered pages, appending new jobs.

        Returns the challenge message when the seed served one (so the caller
        can raise only if *no* seed produced anything), otherwise ``None``. A
        seed whose pagination string carries no ``{page}`` renders its bare URL
        once: the repeated-URL guard stops before re-rendering it ``max_pages``
        times.
        """
        previous: str | None = None
        for page in range(1, self._site_config.max_pages + 1):
            url = self._listing_url_for(seed, page)
            if url == previous:
                break
            previous = url
            try:
                html = self._render(
                    url,
                    self._site_config.listing_ready_selector,
                    self._site_config.listing_wait_seconds,
                )
                self._check_error_page(html, url)
                self._check_challenge(html, url)
            except BrowserChallengeError as exc:
                logger.warning("browser_scraper {}: {}", self._site_config.source_code, exc)
                return str(exc)
            except BrowserFetchError as exc:
                logger.warning("browser_scraper listing page {} failed: {}", url, exc)
                break

            if not self._collect_links(html, seed, page, seen, found, budget):
                break
            if len(found) >= budget:
                break
            time.sleep(self._site_config.inter_request_delay_seconds)
        return None

    def _collect_links(
        self,
        html: str,
        seed: str,
        page: int,
        seen: set[str],
        found: list[dict[str, str]],
        budget: int,
    ) -> bool:
        """Append unseen jobs from one rendered page; False when it listed none."""
        jobs = self._links_on_page(html)
        logger.info(
            "browser_scraper listing {} page {}: {} job link(s) ({} total)",
            seed,
            page,
            len(jobs),
            len(found),
        )
        if not jobs:
            return False
        for job in jobs:
            if job["url"] in seen:
                continue
            seen.add(job["url"])
            found.append(job)
            if len(found) >= budget:
                break
        return True

    def _render_detail(self, url: str) -> str:
        """Render a detail page and return its HTML.

        Navigation happens in the main tab on purpose. The detail URLs were
        already collected from the listing pages, so the listing's scroll
        position and page state are not needed any more, and a new tab is one
        more thing that can fail quietly.

        The wait matters more than it looks: a client-side board answers the
        first request with a shell of a few kilobytes and fills it in
        afterwards. Reading too early yields a page with no description, no
        company and a page title instead of a job title -- which the quality
        gate then rejects for having no body. ethiojobs.net rendered 27 KB
        that way and 272 KB once the wait was right.
        """
        if self._driver is None:
            raise BrowserFetchError("render called before the session was opened")
        try:
            self._navigate(url)
        except Exception as exc:  # noqa: BLE001
            raise BrowserFetchError(f"failed to load detail page {url}: {exc}") from exc
        html = self._wait_for_detail()
        self._detail_pages_visited += 1
        return html

    def _wait_for_detail(self) -> str:
        """Poll the page until it looks rendered, or the budget runs out."""
        deadline = time.monotonic() + self._site_config.detail_wait_seconds
        html = self._driver.page_source if self._driver is not None else ""
        while True:
            html = self._driver.page_source if self._driver is not None else ""
            if self._site_config.detail_ready_selector:
                try:
                    element = self._driver.find_element(
                        "css selector", self._site_config.detail_ready_selector
                    )
                    if element is not None:
                        return self._settle_then_read()
                except Exception:  # noqa: BLE001 - not there yet
                    pass
            elif _looks_rendered(html):
                return self._settle_then_read()
            if time.monotonic() >= deadline:
                return html
            time.sleep(0.5)

    def _settle_then_read(self) -> str:
        """Wait out the settle window, then take the finished page source."""
        seconds = self._site_config.detail_settle_seconds
        if seconds > 0:
            time.sleep(seconds)
        return self._driver.page_source if self._driver is not None else ""

    # -- the interface the HTML pipeline calls --------------------------

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover and render postings.

        Returns the same record shape the HTML client returns, so the HTML
        pipeline (parser, gate, validator, cleaner, persistence) is reused
        unchanged.

        A browser can die mid-run -- the tab is closed by the site, Chrome
        crashes, the driver loses its session. That is not the board being
        empty, so the whole run is retried once with a fresh session rather
        than reported as "no postings found".
        """
        budget = max_jobs or self._site_config.max_jobs_per_run
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                return self._collect(budget)
            except Exception as exc:  # noqa: BLE001 - judged by _is_dead_session
                if not _is_dead_session(exc):
                    raise
                last_error = exc
                logger.warning(
                    "browser_scraper session died (attempt {}/2): {}",
                    attempt,
                    exc,
                )
                self.close_session()
        raise BrowserFetchError(
            f"browser session died twice while scraping {self._site_config.source_code}: "
            f"{last_error}"
        )

    def _detail_html(self, html: str, url: str) -> str:
        """The HTML the parser reads for one rendered posting.

        The rendered page is already in hand, so a site that declares
        ``detail_json_ld`` is mapped from the page itself rather than fetched
        again over HTTP -- the browser framework exists precisely because plain
        HTTP does not get through on these boards. Not every ad publishes the
        block (dubizzle's older ads do not), so a missing block falls back to
        the rendered markup and its CSS selectors; the quality gate then drops
        the record if that markup has no body either.
        """
        if not self._site_config.detail_json_ld:
            return html
        payload = _json_ld_job_posting(html)
        if payload is None:
            logger.warning("browser_scraper: no JobPosting JSON-LD on {}, using markup", url)
            return html
        return mapped_json_html(self._site_config, payload, url)

    def _collect(self, budget: int) -> tuple[list[dict], dict[str, str]]:
        records: list[dict] = []
        failures: dict[str, str] = {}

        self.open_session()
        try:
            discovered = self.discover_detail_paths(budget)
            for job in discovered[: min(budget, self._site_config.max_detail_pages)]:
                try:
                    html = self._render_detail(job["url"])
                    self._check_error_page(html, job["url"])
                    self._check_challenge(html, job["url"])
                    html = self._detail_html(html, job["url"])
                except BrowserChallengeError as exc:
                    failures[job["url"]] = str(exc)
                    logger.warning("browser_scraper {}", exc)
                    break
                except BrowserFetchError as exc:
                    failures[job["url"]] = str(exc)
                    logger.warning("browser_scraper {}", exc)
                    continue
                clean_url = job["url"].split("?", 1)[0].rstrip("/")
                job_id = clean_url.rsplit("/", 1)[-1]
                if self._site_config.id_url_regex:
                    match = re.search(self._site_config.id_url_regex.strip(), job["url"])
                    if match:
                        job_id = match.group(1)
                records.append(
                    {
                        "job_id": job_id if self._site_config.id_from_url else job["url"],
                        "html": html,
                        "url": job["url"],
                        "title_hint": job.get("title", ""),
                        "listing_page": None,
                    }
                )
                time.sleep(self._site_config.inter_request_delay_seconds)
        finally:
            self.close_session()

        logger.info(
            "browser_scraper: {} record(s), {} failure(s)",
            len(records),
            len(failures),
        )
        return records, failures


def looks_like_detail_url(url: str) -> bool:
    """Whether a URL could be a posting page on a job board.

    Used by the config generator to sanity-check a site's own link shape
    before a config is written for it.
    """
    path = urlparse(url).path.lower()
    if len(path) <= 1:
        return False
    for fragment in SECTION_FRAGMENTS:
        if fragment in path:
            return False
    segments = [segment for segment in path.split("/") if segment]
    if not segments or segments[-1] in SECTION_SEGMENTS:
        return False
    return has_job_keyword(path)

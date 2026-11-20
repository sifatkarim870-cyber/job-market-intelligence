"""HTTP client for discovering and fetching Rwandajob.com vacancies.

Discovery walks the server-rendered search directory
``/job-vacancies-search-rwanda`` page by page (page 1 has no query string, page
N is ``?page=N``) until a page carries no new ad links. The live board on
2026-11-20 held 116 offers over 5 pages.

Ad hrefs are ``/job-vacancies-rwanda/<slug>-<id>``. Every sampled slug ends in
the numeric ad id, but the URL is still only the discovery key -- the canonical
id is read from the detail page's JSON-LD ``identifier.value`` in the parser.

robots.txt asks for ``Crawl-delay: 10``. ``_throttle`` enforces that between
*any* two requests, listing or ad page, by measuring from the end of the
previous request rather than sleeping a fixed amount after each one.

A capped run must not re-read only page 1 forever, so the window it fetches is
not simply "the first N rows": the newest ``fresh_rows`` rows are always
included, and the rest of the budget comes from a window that advances one
budget-width per calendar day (``start_offset`` pins it).
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

from .config import RwandaJobSettings
from .exceptions import RwandaJobFetchError, RwandaJobResponseError
from .models import RawRwandaJob

#: The Rwanda path every ad link lives under. Kept narrow on purpose: the footer
#: links to sibling AfricaWork country sites, and a looser pattern would pull
#: their ads into this source.
_AD_HREF_RE = re.compile(r"/job-vacancies-rwanda/([^/?#]+)", re.IGNORECASE)
_TRAILING_ID_RE = re.compile(r"-(\d+)$")


def job_id_from_href(href: str) -> str | None:
    """The discovery id for an ad href, or ``None`` if it is not an ad link.

    A trailing ``-<digits>`` is the ad id; otherwise the slug itself is stable
    across runs and is used as-is.
    """
    match = _AD_HREF_RE.search(href)
    if not match:
        return None
    slug = match.group(1).strip().rstrip("/")
    if not slug:
        return None
    trailing = _TRAILING_ID_RE.search(slug)
    return trailing.group(1) if trailing else slug


class RwandaJobClient:
    """Client for Rwandajob.com (www.rwandajob.com), Rwanda's AfricaWork portal."""

    def __init__(self, settings: RwandaJobSettings | None = None) -> None:
        self._settings = settings or RwandaJobSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
                "Referer": self._settings.base_url + "/",
            }
        )
        self._last_request_at: float | None = None

    def listing_url(self, page: int = 0) -> str:
        """Search-directory URL for a zero-based page number."""
        if page <= 0:
            return self._settings.search_url
        return f"{self._settings.search_url}?page={page}"

    def _throttle(self) -> None:
        """Honour robots.txt Crawl-delay between any two requests."""
        if self._last_request_at is None or self._settings.rate_limit_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.rate_limit_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _fetch_html(self, url: str) -> str:
        """GET with bounded backoff and a robots-aware delay between requests."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds

        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=self._settings.request_timeout)
                if response.status_code in (404, 410):
                    raise RwandaJobFetchError(f"HTTP {response.status_code} fetching {url}")
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Rwandajob.com request {}/{} failed for {}: {}",
                    attempt,
                    self._settings.max_retry_attempts,
                    url,
                    type(exc).__name__,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
            finally:
                self._last_request_at = time.monotonic()

        raise RwandaJobFetchError(f"Rwandajob.com refused {url}: {last_error}") from last_error

    def discover_job_urls(self, max_pages: int | None = None) -> tuple[list[tuple[str, str]], int]:
        """Return ``((url, discovery_id), pages_scraped)`` in board order."""
        pages_to_walk = max_pages or self._settings.max_pages
        found: dict[str, tuple[str, str]] = {}
        pages_scraped = 0
        empty_streak = 0

        for page in range(pages_to_walk):
            page_url = self.listing_url(page)
            try:
                html = self._fetch_html(page_url)
            except RwandaJobFetchError as exc:
                logger.warning("Rwandajob.com listing page {} failed: {}", page, exc)
                break
            pages_scraped += 1

            soup = BeautifulSoup(html, "html.parser")
            new = 0
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"].strip()
                discovery_id = job_id_from_href(href)
                if discovery_id is None or discovery_id in found:
                    continue
                detail_url = (
                    href if href.startswith("http") else urljoin(self._settings.base_url, href)
                )
                found[discovery_id] = (detail_url, discovery_id)
                new += 1

            logger.info(
                "Rwandajob.com listing page {}: {} new ad link(s) ({} total)",
                page,
                new,
                len(found),
            )

            if new == 0:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_empty_pages:
                    break
            else:
                empty_streak = 0

        if not found:
            raise RwandaJobResponseError(
                f"no ad links found in {pages_scraped} page(s) of "
                f"{self._settings.search_url}. An empty result means the markup "
                "changed -- not that the board is empty -- so it is raised rather "
                "than returned empty."
            )

        logger.info(
            "Rwandajob.com discovered {} unique ad(s) across {} page(s).",
            len(found),
            pages_scraped,
        )
        return list(found.values()), pages_scraped

    def rotation_offset(self, window_size: int, tail_size: int) -> int:
        """Where the rotating tail window starts.

        ``start_offset`` pins it. Otherwise it advances one window-width per
        calendar day, so consecutive daily runs tile the tail instead of
        overlapping it.
        """
        if window_size <= 0:
            return 0
        if self._settings.start_offset is not None:
            return self._settings.start_offset % window_size
        step = max(1, tail_size)
        return (date.today().toordinal() * step) % window_size

    def select_window(self, items: list[Any], budget: int) -> list[Any]:
        """The newest ``fresh_rows`` items plus a rotating slice of the rest."""
        if budget >= len(items):
            return list(items)

        fresh_n = min(self._settings.fresh_rows, budget, len(items))
        chosen = list(items[:fresh_n])
        tail = list(items[fresh_n:])
        tail_budget = budget - len(chosen)
        if tail and tail_budget > 0:
            start = self.rotation_offset(len(tail), tail_budget)
            rotated = tail[start:] + tail[:start]
            chosen.extend(rotated[:tail_budget])
        return chosen[:budget]

    def fetch_job_urls(
        self,
        max_pages: int | None = None,
        max_jobs: int | None = None,
    ) -> tuple[list[tuple[str, str]], int]:
        """Discover the board and return the window this run should fetch."""
        discovered, pages_scraped = self.discover_job_urls(max_pages=max_pages)
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        selected = self.select_window(discovered, budget)
        logger.info(
            "Rwandajob.com selected {} of {} discovered ad(s) for detail retrieval (budget={}).",
            len(selected),
            len(discovered),
            budget,
        )
        return selected, pages_scraped

    def fetch_job_detail(self, url: str, job_id: str) -> RawRwandaJob:
        """Fetch raw HTML for a single Rwandajob.com vacancy."""
        return RawRwandaJob(url=url, job_id=job_id, html_content=self._fetch_html(url))

    def fetch_all_details(self, targets: list[tuple[str, str]]) -> list[RawRwandaJob]:
        """Fetch details for a batch of ``(url, discovery_id)`` targets."""
        results: list[RawRwandaJob] = []
        total = len(targets)
        logger.info("Fetching details for {} Rwandajob.com posting(s)...", total)

        for url, discovery_id in targets:
            try:
                results.append(self.fetch_job_detail(url, discovery_id))
            except RwandaJobFetchError as exc:
                logger.warning(
                    "Failed to fetch detail for id={} ({}): {}",
                    discovery_id,
                    url,
                    exc,
                )

        logger.info("Fetched {} Rwandajob.com detail page(s).", len(results))
        return results

"""Fetches raw postings from TopJobs (topjobs.lk, Sri Lanka).

Discovery walks ``/applicant/vacancybyfunctionalarea.jsp?jst=OPEN&pageNo=<n>``
-- the whole open board, newest first -- until a page returns no new job codes
or ``max_listing_pages`` is reached. Pages overlap by one row, so rows are
de-duplicated on the job code.

A capped run must still be useful in two directions, so the window it takes
is not simply "the first N rows":

  * the newest ``fresh_rows`` rows are **always** included, so a run never
    misses what was just posted;
  * the rest of the budget comes from a window that advances one budget-width
    per calendar day (``start_offset`` pins it), so the older tail is covered
    over successive runs instead of the same first page being re-read forever.

Detail pages are fetched one at a time at ``inter_request_delay_seconds``
apart. A failed ad page is not fatal: the listing row is a complete-enough
record on its own, so the record is kept with ``detail_html=None`` and the
failure is reported.
"""

from __future__ import annotations

import time
from datetime import date

import requests
from loguru import logger

from .config import TopJobsLkSettings
from .exceptions import TopJobsLkFetchError, TopJobsLkResponseError
from .parser import parse_listing


class TopJobsLkClient:
    """Fetches postings from TopJobs (Sri Lanka)."""

    def __init__(self, settings: TopJobsLkSettings | None = None) -> None:
        self._settings = settings or TopJobsLkSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def listing_url(self, page: int = 1) -> str:
        url = f"{self._settings.base_url}{self._settings.listing_path}"
        query = self._settings.listing_query
        if page <= 1:
            return f"{url}?{query}"
        return f"{url}?{query}&pageNo={page}"

    def _get(self, url: str) -> str:
        """GET with bounded exponential backoff; raises ``TopJobsLkFetchError``."""
        wait = self._settings.retry_initial_wait_seconds
        last_error: Exception | None = None
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            try:
                response = self._session.get(url, timeout=self._settings.request_timeout_seconds)
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self._settings.max_retry_attempts:
                    break
                logger.warning(
                    "TopJobs request {}/{} failed ({}); retrying in {:.1f}s",
                    attempt,
                    self._settings.max_retry_attempts,
                    type(exc).__name__,
                    wait,
                )
                time.sleep(wait)
                wait = min(wait * 2, self._settings.retry_max_wait_seconds)
        raise TopJobsLkFetchError(f"TopJobs refused {url}: {last_error}") from last_error

    def fetch_listing_page(self, page: int = 1) -> str:
        html = self._get(self.listing_url(page))
        time.sleep(self._settings.inter_request_delay_seconds)
        return html

    def discover_listings(self) -> tuple[dict[str, dict], dict[str, str]]:
        """All open postings in board order (newest first), keyed on job code."""
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_listing_pages + 1):
            try:
                html = self.fetch_listing_page(page)
            except TopJobsLkFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("TopJobs listing page {} failed: {}", page, exc)
                break

            cards = parse_listing(html, page=page, base_url=self._settings.base_url)
            new = 0
            for code, card in cards.items():
                if code not in found:
                    found[code] = card
                    new += 1
            logger.info(
                "TopJobs listing page {}: {} row(s), {} new ({} total)",
                page,
                len(cards),
                new,
                len(found),
            )

            if not cards:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_empty_pages:
                    break
                continue
            if new == 0:
                # Every row was already seen: the pager has wrapped or repeated.
                break
            empty_streak = 0

        if not found and not failures:
            raise TopJobsLkResponseError(
                f"no postings found in {self._settings.max_listing_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result means the markup "
                "changed -- not that the board is empty -- so it is raised rather "
                "than returned empty."
            )
        return found, failures

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

    def select_window(self, cards: dict[str, dict], budget: int) -> list[dict]:
        """The newest ``fresh_rows`` rows plus a rotating slice of the rest."""
        ordered = list(cards.values())
        if budget >= len(ordered):
            return ordered

        fresh_n = min(self._settings.fresh_rows, budget, len(ordered))
        chosen = ordered[:fresh_n]
        tail = ordered[fresh_n:]
        tail_budget = budget - len(chosen)
        if tail and tail_budget > 0:
            start = self.rotation_offset(len(tail), tail_budget)
            rotated = tail[start:] + tail[:start]
            chosen.extend(rotated[:tail_budget])
        return chosen[:budget]

    def fetch_detail(self, url: str) -> str:
        html = self._get(url)
        time.sleep(self._settings.inter_request_delay_seconds)
        return html

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_listings()
        selected = self.select_window(discovered, budget)

        records: list[dict] = []
        for card in selected:
            detail_html: str | None = None
            if self._settings.fetch_details:
                try:
                    detail_html = self.fetch_detail(card["url"])
                except TopJobsLkFetchError as exc:
                    failures[card["jc"]] = str(exc)
                    logger.warning("TopJobs ad {} failed: {}", card["jc"], exc)
            records.append(
                {
                    "job_id": card["jc"],
                    "listing": card,
                    "detail_html": detail_html,
                    "url": card["url"],
                    "listing_page": card["page"],
                }
            )

        if not records and not failures:
            raise TopJobsLkResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info(
            "TopJobs: {} record(s) from {} discovered, {} failure(s)",
            len(records),
            len(discovered),
            len(failures),
        )
        return records, failures

"""Fetches raw postings from JobMail (South Africa).

Plain ``requests`` -- **no browser**. Measured 2026-10-19: the site is
server-rendered and serves both the listing and the detail page completely in
a plain GET.

    /jobs/                      -> 142 KB, 20 posting cards
    /jobs/page2                 -> 20 more, and so on to 400+ pages
    /jobs/<slug>-id-<id>        -> 78 KB, a schema.org JobPosting

robots.txt: ``User-agent: *`` with only ``/setup-alerts/*`` disallowed.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from .config import JobMailSettings
from .exceptions import JobMailFetchError, JobMailResponseError


class JobMailClient:
    """Fetches postings from JobMail over plain HTTP."""

    def __init__(self, settings: JobMailSettings | None = None) -> None:
        self._settings = settings or JobMailSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept-Language": "en-ZA,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> JobMailClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- URLs ---------------------------------------------------------------

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base.rstrip('/')}/page{page}"

    def detail_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        return f"{self._settings.base_url}{href}"

    # -- requests -----------------------------------------------------------

    def _get(self, url: str) -> str:
        last: Exception | None = None
        for attempt in range(1, self._settings.retry_attempts + 1):
            try:
                response = self._session.get(url, timeout=self._settings.timeout_seconds)
                if response.status_code == 200:
                    return response.text
                last = JobMailResponseError(f"HTTP {response.status_code}")
            except requests.RequestException as exc:
                last = exc
            logger.warning(
                "jobmail attempt {}/{} failed for {}: {}",
                attempt,
                self._settings.retry_attempts,
                url[:100],
                str(last)[:110],
            )
            if attempt < self._settings.retry_attempts:
                time.sleep(self._settings.retry_backoff_seconds)
        raise JobMailFetchError(
            f"jobmail request failed after {self._settings.retry_attempts} attempts: "
            f"{url[:110]} -- {last}"
        )

    def fetch_listing_page(self, page: int = 1) -> list[dict]:
        """One page of posting cards."""
        from .parser import parse_listing

        html = self._get(self.listing_url(page))
        cards = parse_listing(html, page)
        logger.info("jobmail listing page {}: {} card(s)", page, len(cards))
        time.sleep(self._settings.inter_request_delay_seconds)
        return cards

    def discover(self) -> tuple[list[dict], dict[str, str]]:
        """Walk listing pages until the budget or the board is exhausted."""
        found: list[dict] = []
        failures: dict[str, str] = {}
        seen: set[str] = set()

        for page in range(1, self._settings.max_list_pages + 1):
            try:
                cards = self.fetch_listing_page(page)
            except JobMailFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobmail listing page {} failed: {}", page, exc)
                break

            if not cards:
                logger.info("jobmail page {} returned no cards -- end of the board", page)
                break

            new = 0
            for card in cards:
                if card["job_id"] in seen:
                    continue
                seen.add(card["job_id"])
                found.append(card)
                new += 1
                # The budget is a cap, not a target: a listing page carries 20
                # postings and the run may ask for fewer, so the walk stops
                # mid-page rather than overshooting.
                if len(found) >= self._settings.max_jobs_per_run:
                    break
            logger.info("jobmail page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found:
            raise JobMailResponseError(
                "no postings discovered. The board holds at least 8,000, so an "
                "empty result means the listing shape changed -- raised rather "
                "than returned, so it cannot look like a successful run."
            )
        return found, failures

    def fetch_detail(self, href: str) -> str | None:
        try:
            html = self._get(self.detail_url(href))
        except JobMailFetchError as exc:
            logger.warning("jobmail detail {} failed: {}", href[:60], exc)
            return None
        finally:
            time.sleep(self._settings.inter_request_delay_seconds)
        return html

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        detail_budget = self._settings.max_details_per_run or budget
        discovered, failures = self.discover()

        selected = discovered[: min(budget, detail_budget)]
        records: list[dict] = []
        for card in selected:
            href = card.get("url")
            html = self.fetch_detail(href) if href else None
            if html is None:
                failures[card["job_id"]] = "detail page unavailable"
            records.append(
                {
                    "job_id": card["job_id"],
                    "html": html,
                    "url": self.detail_url(href) if href else None,
                    "listing_page": card.get("page"),
                    "card": card,
                }
            )

        if not records:
            raise JobMailResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("jobmail: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

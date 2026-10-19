"""Fetches raw postings from Forasna (Egypt).

Plain ``requests`` -- **no browser**. Measured 2026-10-19: the site is
server-rendered and serves both the listing and the detail page completely in
a plain GET.

    /وظائف-خالية?start=20                -> 281 KB, 20 postings
    /job/p/<slug>-444468                  -> 139 KB, a JSON-LD JobPosting

The listing is the site's own search page, paginated by an **offset**
(``?start=``), 20 postings a page, 2,852 postings on the board.

One thing worth naming, because it looks like a bug in the client and is not:
the site publishes a nominal all-jobs route, ``/a/وظائف-مصر``, which returns
HTTP 200 and 281 KB with **no job links on it at all**. The search page is
used instead.

robots.txt: ``User-agent: *`` with no ``Disallow``.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from .config import ForasnaSettings
from .exceptions import ForasnaFetchError, ForasnaResponseError


class ForasnaClient:
    """Fetches postings from Forasna over plain HTTP."""

    def __init__(self, settings: ForasnaSettings | None = None) -> None:
        self._settings = settings or ForasnaSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept-Language": "ar,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ForasnaClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- URLs ---------------------------------------------------------------

    def listing_url(self, page: int = 1) -> str:
        """The listing URL for a 1-based page number."""
        offset = (page - 1) * self._settings.page_size
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return f"{base}?start={offset}"

    def detail_url(self, slug: str) -> str:
        return f"{self._settings.base_url}{self._settings.detail_path}/{slug}"

    # -- requests -----------------------------------------------------------

    def _get(self, url: str) -> str:
        last: Exception | None = None
        for attempt in range(1, self._settings.retry_attempts + 1):
            try:
                response = self._session.get(url, timeout=self._settings.timeout_seconds)
                if response.status_code == 200:
                    return response.text
                last = ForasnaResponseError(f"HTTP {response.status_code}")
            except requests.RequestException as exc:
                last = exc
            logger.warning(
                "forasna attempt {}/{} failed for {}: {}",
                attempt,
                self._settings.retry_attempts,
                url[:100],
                str(last)[:110],
            )
            if attempt < self._settings.retry_attempts:
                time.sleep(self._settings.retry_backoff_seconds)
        raise ForasnaFetchError(
            f"forasna request failed after {self._settings.retry_attempts} attempts: "
            f"{url[:110]} -- {last}"
        )

    def fetch_listing_page(self, page: int = 1) -> list[tuple[str, str]]:
        """One page of ``(slug, id)`` pairs."""
        from .parser import parse_listing

        html = self._get(self.listing_url(page))
        postings = parse_listing(html)
        logger.info("forasna listing page {}: {} posting(s)", page, len(postings))
        time.sleep(self._settings.inter_request_delay_seconds)
        return postings

    def discover(self) -> tuple[list[tuple[str, str]], dict[str, str]]:
        """Walk listing pages until the budget or the board is exhausted."""
        found: list[tuple[str, str]] = []
        failures: dict[str, str] = {}
        seen: set[str] = set()

        for page in range(1, self._settings.max_list_pages + 1):
            try:
                postings = self.fetch_listing_page(page)
            except ForasnaFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("forasna listing page {} failed: {}", page, exc)
                break

            if not postings:
                logger.info("forasna page {} returned no postings -- end of the board", page)
                break

            new = 0
            for slug, job_id in postings:
                if job_id in seen:
                    continue
                seen.add(job_id)
                found.append((slug, job_id))
                new += 1
                # The budget is a cap, not a target: a listing page carries
                # 20 postings and the run may ask for fewer, so the walk
                # stops mid-page rather than overshooting.
                if len(found) >= self._settings.max_jobs_per_run:
                    break
            logger.info("forasna page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found:
            raise ForasnaResponseError(
                "no postings discovered. The board reports 2852 postings, so an "
                "empty result means the listing shape changed -- raised rather "
                "than returned, so it cannot look like a successful run."
            )
        return found, failures

    def fetch_detail(self, slug: str) -> str | None:
        try:
            html = self._get(self.detail_url(slug))
        except ForasnaFetchError as exc:
            logger.warning("forasna detail {} failed: {}", slug[:50], exc)
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
        for slug, job_id in selected:
            records.append(
                {
                    "slug": slug,
                    "job_id": job_id,
                    "html": self.fetch_detail(slug),
                    "url": self.detail_url(slug),
                    "listing_page": None,
                }
            )
        failed = [r["job_id"] for r in records if r["html"] is None]
        for job_id in failed:
            failures[job_id] = "detail page unavailable"

        if not records:
            raise ForasnaResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("forasna: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

"""Fetches raw job data from Emploitic.

This module's only responsibility: make the HTTP requests (with retries
for transient failures), extract the embedded JSON job payload from the
server-rendered listing pages, and hand back raw dictionaries. It does not
validate individual job fields — that is ``parser.py``'s job. Same
fetch/validate/decide separation the other scrapers establish.

Where the data lives (confirmed live, 2026-10-04)
-------------------------------------------------
Emploitic has no published JSON API. Its Next.js frontend server-renders
the job-search result as JSON inside the listing page's
``<script id="__NEXT_DATA__" type="application/json">`` tag, at
``props.pageProps.searchResult`` (``{data, totalPages, currentPage,
total, aggregateCount}``). Each ``data`` entry carries ``id``, ``title``,
``alias``, ``description`` (HTML), ``location[]``, ``contractType[]``,
``workMode``, ``jobLevel[]``, ``profession``, ``tags[]``, ``company``,
and ``publishedAt``. Pagination is ``?page=N`` on the listing URL
(20 jobs per page), confirmed by two live fetches returning distinct
result sets and matching ``currentPage``.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_html
from job_market_intel.common.retry import call_with_retry

from .config import EmploiticSettings
from .exceptions import EmploiticFetchError, EmploiticResponseError

_NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)


class EmploiticClient:
    """Fetches the current Emploitic job-listing pages."""

    def __init__(self, settings: EmploiticSettings | None = None) -> None:
        self._settings = settings or EmploiticSettings()

    def _fetch_listing_page(self, page: int) -> str:
        url = f"{self._settings.base_url}?page={page}"
        try:
            return call_with_retry(
                fetch_html,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
            )
        except TransientHTTPError as exc:
            raise EmploiticFetchError(
                f"Could not reach Emploitic after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise EmploiticFetchError(f"Emploitic request failed permanently: {exc}") from exc

    def _extract_search_result(self, page_html: str, page: int) -> dict:
        match = _NEXT_DATA_PATTERN.search(page_html)
        if not match:
            raise EmploiticResponseError(
                f"Emploitic page {page} contained no __NEXT_DATA__ JSON payload. "
                "The frontend's rendering shape may have changed."
            )
        try:
            payload = json.loads(match.group(1))
        except ValueError as exc:
            raise EmploiticResponseError(
                f"Emploitic page {page}'s __NEXT_DATA__ payload was not valid JSON: {exc}"
            ) from exc
        try:
            search_result = payload["props"]["pageProps"]["searchResult"]
        except (KeyError, TypeError) as exc:
            raise EmploiticResponseError(
                f"Emploitic page {page}'s JSON did not contain "
                f"props.pageProps.searchResult: {exc}"
            ) from exc
        if not isinstance(search_result, dict) or not isinstance(search_result.get("data"), list):
            raise EmploiticResponseError(
                f"Emploitic page {page}'s searchResult had no 'data' list. "
                "The payload shape may have changed."
            )
        return search_result

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch up to ``max_pages_per_run`` listing pages.

        Returns:
            A list of raw job dictionaries in Emploitic's own field naming,
            flattened across pages. May be shorter than
            ``max_pages_per_run * 20`` once the last reported page is
            reached (``totalPages`` from the first page's payload).

        Raises:
            EmploiticFetchError: If a page could not be fetched after
                exhausting retries.
            EmploiticResponseError: If a page's payload wasn't a usable
                job list.
        """
        all_jobs: list[dict] = []
        total_pages: int | None = None

        for page in range(1, self._settings.max_pages_per_run + 1):
            logger.info("Fetching Emploitic listing page {}.", page)
            html = self._fetch_listing_page(page)
            search_result = self._extract_search_result(html, page)
            total_pages = search_result.get("totalPages") if total_pages is None else total_pages
            page_jobs = [entry for entry in search_result["data"] if isinstance(entry, dict)]
            all_jobs.extend(page_jobs)
            logger.info(
                "Emploitic page {}: {} jobs (total reported: {}).",
                page,
                len(page_jobs),
                search_result.get("total"),
            )
            if not page_jobs:
                break
            if isinstance(total_pages, int) and page >= total_pages:
                break

        if not all_jobs:
            raise EmploiticResponseError(
                "Emploitic returned zero recognizable job records across all "
                "fetched pages. The payload shape may have changed, or this "
                "may be a blocked/empty response."
            )
        logger.info("Fetched {} job records from Emploitic.", len(all_jobs))
        return all_jobs

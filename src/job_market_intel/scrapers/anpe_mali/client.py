"""Fetches raw ANPE Mali job records from the WP Job Manager REST API.

The module's only responsibility: walk the keyless ``job-listings``
endpoint and hand back raw dictionaries. Field validation is
``parser.py``'s job -- the same fetch/validate separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
``GET https://anpe-mali.org/wp-json/wp/v2/job-listings`` with
``per_page=100&page=N`` answers a JSON array of listing objects and sends
``X-WP-Total: 15`` / ``X-WP-TotalPages: 1``. The board's own sitemap
(``/wp-sitemap-posts-job_listing-1.xml``) lists the same 15 pages, so the
count is cross-checked. ``_embed=wp:featuredmedia`` adds the company-logo
media object to each row in the same request, so no per-listing detail
call is made.

No key, cookie, token or proxy: a browser ``User-Agent`` is enough, and
``robots.txt`` only disallows ``/wp-admin/`` (never fetched).

Failure taxonomy
----------------
* A page that still fails transiently after every attempt propagates as
  ``AnpeMaliFetchError`` -- without discovery there is nothing to show.
* A permanent 4xx (a wrong endpoint, say) is a fetch error too.
* A non-JSON body, or JSON that is not an array of objects, raises
  ``AnpeMaliResponseError`` (shape change / maintenance page -- fails
  loudly rather than silently producing zero jobs).
* An empty first page is a response error; an empty later page simply
  ends pagination.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import AnpeMaliSettings
from .exceptions import AnpeMaliFetchError, AnpeMaliResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AnpeMaliClient:
    """Walks the WP Job Manager REST ``job-listings`` endpoint."""

    def __init__(self, settings: AnpeMaliSettings | None = None) -> None:
        self._settings = settings or AnpeMaliSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> AnpeMaliClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch every listing on the board, newest-first.

        The endpoint is ordered newest-first via ``orderby=date``.
        ``max_jobs_per_run`` caps a run (the whole board is 15 rows at
        scoping, so the default 200 reads it all).

        Raises:
            AnpeMaliFetchError: A page failed after retries, or a permanent
                4xx was returned.
            AnpeMaliResponseError: The body was not a JSON array of
                listings, or the first page was empty.
        """
        rows: list[dict] = []
        page = 1
        total_pages = 1

        while page <= self._settings.max_pages and len(rows) < self._settings.max_jobs_per_run:
            listings, total_pages = self._fetch_page(page)

            if not listings:
                if page == 1:
                    raise AnpeMaliResponseError(
                        "ANPE Mali answered an empty first page for the job-listings "
                        "endpoint; the endpoint probably moved"
                    )
                break

            remaining = self._settings.max_jobs_per_run - len(rows)
            rows.extend(listings[:remaining])

            if page >= total_pages:
                break
            page += 1
            if self._settings.fetch_delay_seconds:
                time.sleep(self._settings.fetch_delay_seconds)

        logger.info(
            "ANPE Mali discovery selected {} listing rows ({} page(s) of {} reported).",
            len(rows),
            page,
            total_pages,
        )
        return rows

    def _fetch_page(self, page: int) -> tuple[list[dict], int]:
        """Fetch one page and return ``(listings, total_pages)``."""
        params: dict[str, Any] = {
            "per_page": self._settings.per_page,
            "page": page,
            "orderby": "date",
            "order": "desc",
            "_embed": "wp:featuredmedia",
        }
        try:
            response = call_with_retry(
                self._get,
                params=params,
                retry_exception_types=(TransientHTTPError,),
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except PermanentHTTPError as exc:
            raise AnpeMaliFetchError(
                f"ANPE Mali job-listings endpoint rejected page {page}: {exc}"
            ) from exc
        except TransientHTTPError as exc:
            raise AnpeMaliFetchError(
                f"ANPE Mali job-listings endpoint failed page {page} after retries: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AnpeMaliResponseError(
                f"ANPE Mali page {page} was not JSON ({len(response.content)} bytes)"
            ) from exc

        if not isinstance(payload, list):
            raise AnpeMaliResponseError(
                f"ANPE Mali page {page} was {type(payload).__name__}, expected a listing array"
            )

        reported = response.headers.get("X-WP-TotalPages") or "1"
        try:
            total_pages = max(1, int(reported))
        except ValueError:
            total_pages = max(1, page)
        return payload, total_pages

    def _get(self, *, params: dict[str, Any]) -> requests.Response:
        """One GET, translating transport/status failures into retry types."""
        try:
            response = self._session.get(
                self._settings.listings_url,
                params=params,
                timeout=self._settings.request_timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientHTTPError(f"{type(exc).__name__}: {exc}") from exc

        if response.status_code in _RETRYABLE_STATUS:
            raise TransientHTTPError(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PermanentHTTPError(f"HTTP {response.status_code}")
        return response

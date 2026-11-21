"""Fetches raw ANPE Burkina Faso job posts from the WordPress REST API.

The module's only responsibility: walk the keyless posts endpoint for the
``offres-demplois`` category and hand back raw dictionaries. Field
validation is ``parser.py``'s job -- the same fetch/validate separation the
other scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
``GET https://www.anpe.gov.bf/wp-json/wp/v2/posts`` with
``categories=77&per_page=100&page=N`` answers a JSON array of post objects
and sends ``X-WP-Total: 97`` / ``X-WP-TotalPages: 1``. No key, cookie,
token or proxy: a browser ``User-Agent`` is enough, and the public
``robots.txt`` explicitly allows ``/``.

The host is a single slow Apache/WordPress box that intermittently times
out or answers HTTP 500 for a few seconds at a time; the measured pattern
at scoping was "robots.txt and the REST API answer, while a page GET may
need a second attempt". The client therefore treats timeouts,
connection-resets, 429 and 5xx as transient and retries them with
exponential backoff, exactly like the other API clients.

Failure taxonomy
----------------
* A page that still fails transiently after every attempt propagates as
  ``AnpeBfFetchError`` -- without discovery there is nothing to show.
* A permanent 4xx (a wrong category id, say) is a fetch error too.
* A non-JSON body, or JSON that is not an array of objects, raises
  ``AnpeBfResponseError`` (shape change / maintenance page -- fails
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

from .config import AnpeBfSettings
from .exceptions import AnpeBfFetchError, AnpeBfResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Only these fields are needed; asking for less keeps each page small and
#: the host (which is slow) has less to render.
_FIELDS = "id,date,modified,link,title,content,excerpt"


class AnpeBfClient:
    """Walks the WordPress REST posts endpoint for the offers category."""

    def __init__(self, settings: AnpeBfSettings | None = None) -> None:
        self._settings = settings or AnpeBfSettings()
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

    def __enter__(self) -> AnpeBfClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch every post in the offers category, newest-first.

        The endpoint is already ordered newest-first; ``max_jobs_per_run``
        caps a run (the whole category is 97 rows at scoping, so the default
        200 reads it all).

        Raises:
            AnpeBfFetchError: A page failed after retries, or a permanent
                4xx was returned.
            AnpeBfResponseError: The body was not a JSON array of posts, or
                the first page was empty.
        """
        rows: list[dict] = []
        page = 1
        total_pages = 1

        while page <= self._settings.max_pages and len(rows) < self._settings.max_jobs_per_run:
            posts, total_pages = self._fetch_page(page)

            if not posts:
                if page == 1:
                    raise AnpeBfResponseError(
                        "ANPE Burkina Faso answered an empty first page for category "
                        f"{self._settings.category_id}; the category or endpoint probably moved"
                    )
                break

            remaining = self._settings.max_jobs_per_run - len(rows)
            rows.extend(posts[:remaining])

            if page >= total_pages:
                break
            page += 1
            if self._settings.fetch_delay_seconds:
                time.sleep(self._settings.fetch_delay_seconds)

        logger.info(
            "ANPE Burkina Faso discovery selected {} post rows ({} page(s) of {} reported).",
            len(rows),
            page,
            total_pages,
        )
        return rows

    def _fetch_page(self, page: int) -> tuple[list[dict], int]:
        """Fetch one page and return ``(posts, total_pages)``."""
        params: dict[str, Any] = {
            "categories": self._settings.category_id,
            "per_page": self._settings.per_page,
            "page": page,
            "_fields": _FIELDS,
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
            raise AnpeBfFetchError(
                f"ANPE Burkina Faso posts endpoint rejected page {page}: {exc}"
            ) from exc
        except TransientHTTPError as exc:
            raise AnpeBfFetchError(
                f"ANPE Burkina Faso posts endpoint failed page {page} after retries: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AnpeBfResponseError(
                f"ANPE Burkina Faso page {page} was not JSON ({len(response.content)} bytes)"
            ) from exc

        if not isinstance(payload, list):
            raise AnpeBfResponseError(
                f"ANPE Burkina Faso page {page} was {type(payload).__name__}, expected a post array"
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
                self._settings.posts_url,
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

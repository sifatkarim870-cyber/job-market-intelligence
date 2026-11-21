"""Fetches raw job data from Zangia.mn.

This module's only responsibility: walk the open listing paginator, then
hydrate each row from the open detail endpoint, and hand back raw
dictionaries. It does not validate individual job fields -- that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
Zangia is a newest-first cursor of listing rows, each hydrated by a second
keyless call. Both are plain GETs on the HR API host:

* **Listing** -- ``GET
  https://hr-api.zangia.mn/api/job/public/list/search`` returns
  ``{data, page, limit, total, totalPages}`` where ``data`` holds up to
  ``limit`` rows. The default page size is 90 and ``limit`` accepts at
  least 500; the feed is newest-first by ``sortTime`` and past the last
  page ``data`` is empty. The total was 6,099 live rows at scoping.
* **Detail** -- ``GET
  https://hr-api.zangia.mn/api/job/public/detail/<code>`` returns
  ``{data, message}`` where ``data`` is the complete record. ``code`` is
  the listing row's own URL slug (the public page is
  ``https://zangia.mn/job/<code>``).

No auth, no cookie, no signing: a browser ``User-Agent`` plus
``Accept: application/json`` and an ``Origin``/``Referer`` of the public
site answered 200 on every probe.

robots.txt posture
-----------------
There is NO readable ``robots.txt`` on the property: ``zangia.mn``,
``www.zangia.mn``, ``hr-api.zangia.mn`` and ``new-api.zangia.mn`` all
return HTTP 404. The project owner reviewed that and approved this source
on 2026-11-21, recording the 404s as an observed fact (RFC 9309's
allow-all posture for an absent policy) rather than silently treating
them as permission -- see ``config.py``.

Failure taxonomy, mirroring the TimesJobs client (plus a detail phase):

* A **listing page GET** failing after retries (transient exhaustion) or
  failing permanently (a non-retryable 4xx) propagates as
  ``ZangiaFetchError``: without the discovery cursor there is nothing to
  show for the run.
* A **detail GET** failing after retries is logged and that single job is
  skipped, never aborting the batch -- one flaky detail must not discard
  the rest of the run.
* A non-JSON or non-object listing envelope propagates as a fetch error
  too (shape change / bot wall -- a fully broken site fails loudly).
* An envelope without a usable ``data`` list, an empty first page (past
  ``start_page`` or a block page), or rows that all lack a ``code`` raise
  ``ZangiaResponseError`` -- never a silent zero-jobs no-op.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import ZangiaSettings
from .exceptions import ZangiaFetchError, ZangiaResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Stop after this many consecutive pages that add no new ``code`` -- a
#: guard against a paginator that stops honoring ``page`` (an infinite
#: cursor), independent of the reported ``totalPages``.
_MAX_PAGES_WITHOUT_GROWTH = 3


class ZangiaClient:
    """Walks the open listing paginator and hydrates each row's detail."""

    def __init__(self, settings: ZangiaSettings | None = None) -> None:
        self._settings = settings or ZangiaSettings()
        # One keep-alive session: a default run is ~3 listing GETs plus one
        # detail GET per job, so reusing the pool matters.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "mn,en;q=0.9",
                "Origin": self._settings.web_base_url,
                "Referer": f"{self._settings.web_base_url}/",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _request(self, url: str, *, params: dict | None, what: str) -> requests.Response:
        """Send one GET with retries; classify failures into the shared taxonomy."""
        settings = self._settings

        def _do() -> requests.Response:
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=settings.request_timeout_seconds,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientHTTPError(str(exc)) from exc
            except requests.RequestException as exc:
                raise PermanentHTTPError(str(exc)) from exc

            if response.status_code in _RETRYABLE_STATUS:
                raise TransientHTTPError(f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise PermanentHTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            return response

        try:
            return call_with_retry(
                _do,
                retry_exception_types=TransientHTTPError,
                max_attempts=settings.max_retry_attempts,
                initial_wait_seconds=settings.retry_initial_wait_seconds,
                max_wait_seconds=settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise ZangiaFetchError(
                f"Could not reach Zangia ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise ZangiaFetchError(f"Zangia request failed permanently ({what}): {exc}") from exc

    # -- discovery -------------------------------------------------------
    def _get_listing_page(self, page: int) -> dict:
        """GET one listing page and return the paginator envelope."""
        params = {"page": page, "limit": self._settings.page_size}
        response = self._request(
            self._settings.list_url, params=params, what=f"listing page {page}"
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ZangiaFetchError(
                f"Zangia listing page {page} returned non-JSON (payload "
                f"shape change or block?): {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ZangiaFetchError(
                f"Zangia listing page {page} returned a non-object JSON payload."
            )
        return payload

    @staticmethod
    def _rows_or_raise(payload: dict) -> list:
        """The envelope's ``data`` list, or a response error on a shape change."""
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ZangiaResponseError(
                "Zangia listing envelope has no usable data list (keys: "
                f"{sorted(payload)}). The payload shape may have changed."
            )
        return rows

    @staticmethod
    def _collect_rows(rows: list, seen: set[str], out: list[dict]) -> int:
        """Append new unique listing rows to ``out``; return how many were added."""
        added = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(row)
            added += 1
        return added

    def _select_rows(self) -> list[dict]:
        """Listing rows from ``start_page`` until the window fills or the cursor ends."""
        settings = self._settings
        limit = settings.max_jobs_per_run
        page = settings.start_page
        first_page = page
        total_pages: int | None = None
        selected: list[dict] = []
        seen: set[str] = set()
        stagnant = 0

        while len(selected) < limit:
            payload = self._get_listing_page(page)
            rows = self._rows_or_raise(payload)
            if not rows:
                break  # past the end of the cursor (empty data list)

            if total_pages is None:
                reported = payload.get("totalPages")
                if isinstance(reported, int) and reported > 0:
                    total_pages = reported

            added = self._collect_rows(rows, seen, selected)
            stagnant = stagnant + 1 if added == 0 else 0
            if stagnant >= _MAX_PAGES_WITHOUT_GROWTH:
                break
            page += 1
            if total_pages is not None and page > total_pages:
                break
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "Zangia discovery selected {} unique listing rows (window {}, "
            "listing pages {}-{} read).",
            len(selected),
            limit,
            first_page,
            page - 1,
        )
        return selected

    # -- detail ----------------------------------------------------------
    def _fetch_detail(self, code: str) -> dict | None:
        """GET one detail record; None (logged) when the call fails.

        A single detail failure is a skipped job, not a failed run: the
        listing row still hydrates a partial record, but a detail that
        cannot be read is better dropped than guessed at.
        """
        url = self._settings.detail_url_template.format(code=code)
        try:
            response = self._request(url, params=None, what=f"detail {code}")
        except ZangiaFetchError as exc:
            logger.warning("Skipping Zangia detail {} (fetch failed): {}", code, exc)
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Skipping Zangia detail {} (non-JSON response).", code)
            return None
        if not isinstance(payload, dict):
            logger.warning("Skipping Zangia detail {} (non-object payload).", code)
            return None
        detail = payload.get("data")
        if not isinstance(detail, dict):
            # A 200 with data:null is the API's "not found" ("ES Job not
            # found" was a 404); treat it as an absent detail, not a crash.
            logger.warning("Skipping Zangia detail {} (no data object).", code)
            return None
        return detail

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk the listing cursor and hydrate each row's detail.

        Returns:
            Raw records ``{"url": public job URL, "listing": the listing
            row dict, "detail": the detail dict or None}``.

        Raises:
            ZangiaFetchError: If a listing page GET failed after exhausting
                retries or the endpoint stopped serving JSON objects.
            ZangiaResponseError: If the first page returned zero rows
                (past ``start_page`` / format change / block), the envelope
                lost its ``data`` list, or no selected row had a ``code``.
        """
        rows = self._select_rows()
        if not rows:
            raise ZangiaResponseError(
                "Zangia listing returned zero rows on page "
                f"{self._settings.start_page}. The listing format may have "
                "changed, the site may be unreachable, or start_page is "
                "past the end of the cursor."
            )

        jobs: list[dict] = []
        for index, row in enumerate(rows):
            code = str(row.get("code") or "")
            if not code:
                logger.warning(
                    "Skipping Zangia listing row {}: no usable code.",
                    row.get("id", f"<index {index}>"),
                )
                continue
            detail = self._fetch_detail(code)
            jobs.append(
                {
                    "url": f"{self._settings.web_base_url}/job/{code}",
                    "listing": row,
                    "detail": detail,
                }
            )
            if self._settings.fetch_delay_seconds and index + 1 < len(rows):
                time.sleep(self._settings.fetch_delay_seconds)

        if not jobs:
            raise ZangiaResponseError(
                "Zangia returned zero usable job records across all "
                "selected rows (no code on any). The payload shape may have "
                "changed, or the responses were blocked/empty."
            )

        logger.info(
            "Fetched {} Zangia job records ({} rows selected, {} hydrated details).",
            len(jobs),
            len(rows),
            sum(1 for job in jobs if job["detail"] is not None),
        )
        return jobs

"""Fetches raw job data from XpressJobs.

This module's only responsibility: walk the open listing feed, then
hydrate each row from the open detail endpoint, and hand back raw
dictionaries. It does not validate individual job fields -- that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-11-28)
--------------------------------------------------
XpressJobs is a React SPA whose HTML shell is empty, so the jobs come from
a keyless public JSON API rather than the DOM. Both calls are plain GETs:

* **Listing** -- ``GET https://xpress.jobs/api/jobs/searchJobs`` returns a
  **bare JSON array** (not an envelope) of listing rows. ``page`` is
  1-based, ``pageSize`` is capped at 100 server-side, and
  ``sortBy=SortedCreateDate DESC`` (the public page's "Recent" option) is
  the only value that makes the feed deterministic and pageable -- the
  default ``NEWID()`` re-randomises every call and would double-fetch.
  Each row carries ``recordCount`` (the board's live total).
* **Detail** -- ``GET
  https://xpress.jobs/api/jobs/publishedJob?jobId=<id>`` returns the full
  record: the HTML ``jobInfo`` body, salary strings, ``sectors``, the
  nested ``jobItem`` and the ``organization`` block. No envelope either.
* **Public page** -- ``https://xpress.jobs/jobs/view/<jobId>`` (HTTP 200).

robots.txt posture
------------------
``https://xpress.jobs/robots.txt`` is HTTP 200, 114 bytes: a single
``User-agent: *`` group whose ``Disallow:`` directive is **empty** (so
everything is allowed) plus a ``Sitemap:`` line. There is no ``Crawl-
delay``. No auth, no cookie, no signing: a browser ``User-Agent`` plus an
``Origin``/``Referer`` of the public site answered 200 on every probe.

Failure taxonomy, mirroring the Zangia client:

* A **listing page GET** failing after retries, or returning non-JSON /
  a non-array payload, propagates as ``XpressJobsFetchError``: without the
  discovery cursor there is nothing to show for the run.
* A **detail GET** failing after retries is logged and that single job is
  skipped, never aborting the batch -- one flaky detail must not discard
  the rest of the run.
* An empty first page (past ``start_page`` or a block page) or rows that
  all lack a ``jobId`` raise ``XpressJobsResponseError`` -- never a silent
  zero-jobs no-op.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import XpressJobsSettings
from .exceptions import XpressJobsFetchError, XpressJobsResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Stop after this many consecutive pages that add no new ``jobId`` -- a
#: guard against a paginator that stops honoring ``page`` (an infinite
#: cursor).
_MAX_PAGES_WITHOUT_GROWTH = 3


class XpressJobsClient:
    """Walks the open listing feed and hydrates each row's detail."""

    def __init__(self, settings: XpressJobsSettings | None = None) -> None:
        self._settings = settings or XpressJobsSettings()
        # One keep-alive session: a default run is a couple of listing GETs
        # plus one detail GET per job, so reusing the pool matters.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en,si;q=0.9",
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
            raise XpressJobsFetchError(
                f"Could not reach XpressJobs ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise XpressJobsFetchError(
                f"XpressJobs request failed permanently ({what}): {exc}"
            ) from exc

    # -- discovery -------------------------------------------------------
    def _get_listing_page(self, page: int) -> list:
        """GET one listing page and return its bare JSON array."""
        params = {
            "page": page,
            "pageSize": self._settings.page_size,
            "sortBy": self._settings.sort_by,
            "keyword": "",
        }
        response = self._request(
            self._settings.search_url, params=params, what=f"listing page {page}"
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise XpressJobsFetchError(
                f"XpressJobs listing page {page} returned non-JSON (payload "
                f"shape change or block?): {exc}"
            ) from exc
        if not isinstance(payload, list):
            got = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
            raise XpressJobsFetchError(
                f"XpressJobs listing page {page} returned a non-array JSON "
                f"payload (got: {got})."
            )
        return payload

    @staticmethod
    def _collect_rows(rows: list, seen: set[str], out: list[dict]) -> int:
        """Append new unique listing rows to ``out``; return how many were added."""
        added = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("jobId") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            out.append(row)
            added += 1
        return added

    def _select_rows(self) -> list[dict]:
        """Listing rows from ``start_page`` until the window fills or the feed ends."""
        settings = self._settings
        limit = settings.max_jobs_per_run
        page = settings.start_page
        first_page = page
        selected: list[dict] = []
        seen: set[str] = set()
        stagnant = 0

        while len(selected) < limit:
            rows = self._get_listing_page(page)
            if not rows:
                break  # past the end of the feed (empty array)

            added = self._collect_rows(rows, seen, selected)
            stagnant = stagnant + 1 if added == 0 else 0
            if stagnant >= _MAX_PAGES_WITHOUT_GROWTH:
                break
            page += 1
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "XpressJobs discovery selected {} unique listing rows (window {}, "
            "listing pages {}-{} read).",
            len(selected),
            limit,
            first_page,
            page - 1,
        )
        return selected

    # -- detail ----------------------------------------------------------
    def _fetch_detail(self, job_id: str) -> dict | None:
        """GET one detail record; None (logged) when the call fails.

        A single detail failure is a skipped job, not a failed run: the
        listing row still hydrates a partial record, but a detail that
        cannot be read is better dropped than guessed at.
        """
        try:
            response = self._request(
                self._settings.detail_url, params={"jobId": job_id}, what=f"detail {job_id}"
            )
        except XpressJobsFetchError as exc:
            logger.warning("Skipping XpressJobs detail {} (fetch failed): {}", job_id, exc)
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Skipping XpressJobs detail {} (non-JSON response).", job_id)
            return None
        if not isinstance(payload, dict):
            logger.warning("Skipping XpressJobs detail {} (non-object payload).", job_id)
            return None
        if not payload.get("jobId"):
            logger.warning("Skipping XpressJobs detail {} (no jobId in payload).", job_id)
            return None
        return payload

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk the listing feed and hydrate each row's detail.

        Returns:
            Raw records ``{"url": public job URL, "listing": the listing
            row dict, "detail": the detail dict or None}``.

        Raises:
            XpressJobsFetchError: If a listing page GET failed after
                exhausting retries or the endpoint stopped serving JSON
                arrays.
            XpressJobsResponseError: If the first page returned zero rows
                (past ``start_page`` / format change / block) or no
                selected row had a ``jobId``.
        """
        rows = self._select_rows()
        if not rows:
            raise XpressJobsResponseError(
                "XpressJobs listing returned zero rows on page "
                f"{self._settings.start_page}. The listing format may have "
                "changed, the site may be unreachable, or start_page is "
                "past the end of the feed."
            )

        jobs: list[dict] = []
        for index, row in enumerate(rows):
            job_id = str(row.get("jobId") or "")
            if not job_id:
                logger.warning(
                    "Skipping XpressJobs listing row {}: no usable jobId.",
                    row.get("jobId", f"<index {index}>"),
                )
                continue
            detail = self._fetch_detail(job_id)
            jobs.append(
                {
                    "url": f"{self._settings.web_base_url}/jobs/view/{job_id}",
                    "listing": row,
                    "detail": detail,
                }
            )
            if self._settings.fetch_delay_seconds and index + 1 < len(rows):
                time.sleep(self._settings.fetch_delay_seconds)

        if not jobs:
            raise XpressJobsResponseError(
                "XpressJobs returned zero usable job records across all "
                "selected rows (no jobId on any). The payload shape may have "
                "changed, or the responses were blocked/empty."
            )

        logger.info(
            "Fetched {} XpressJobs job records ({} rows selected, {} hydrated details).",
            len(jobs),
            len(rows),
            sum(1 for job in jobs if job["detail"] is not None),
        )
        return jobs

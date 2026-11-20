"""Fetches raw job data from TimesJobs.

This module's only responsibility: walk the open listing paginator, then
hydrate each row from the open detail endpoint, and hand back raw
dictionaries. It does not validate individual job fields -- that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
TimesJobs is a date-descending cursor of listing rows, each hydrated by a
second keyless call:

* **Listing** -- ``POST
  https://tjapi.timesjobs.com/search/api/v1/search/jobs/list`` with body
  ``{"keyword", "location", "experience", "page", "size", "jobFunctions",
  "company", "industry", "functionAreaId", "jobFunction"}`` returns
  ``{total, page, size, totalPages, jobs}`` where ``jobs`` holds up to
  ``size`` rows. The default feed is newest-first by ``postDate`` (page 1
  and page 2 were entirely the same day at scoping), ``size`` accepts at
  least 500, and past the last page ``jobs`` is simply empty.
* **Detail** -- ``GET
  https://tjapi.timesjobs.com/job-api/api/jobs/public/<token>`` where
  ``token`` is everything after ``jobid-`` in a listing row's
  ``jobDetailUrl`` (including its trailing ``&source=srp``). It is sent
  as one URL-encoded path segment; the site's own ``__PLUS__``/
  ``__SLASH__`` escapes resolve to HTTP 200 unchanged.

No auth, no cookie, no signing: a browser ``User-Agent`` plus
``Content-Type: application/json`` and an ``Origin``/``Referer`` of the
public site answered 200 on every probe.

robots.txt posture
------------------
The public site's ``robots.txt`` (HTTP 200) is a generic ``User-agent:
*`` group that allows everything except ``/timesJobWebApp/``,
``/logout.html``, ``/AutoLogin.html`` and ``/times_logout`` -- none used
here. The API host ``tjapi.timesjobs.com`` serves no readable
``robots.txt`` (HTTP 502 for ``/robots.txt`` and ``/``); the project
owner reviewed that and approved this source on 2026-11-21 (see
``config.py``).

Failure taxonomy, mirroring the Irantalent client (plus a detail phase):

* A **listing page POST** failing after retries (transient exhaustion) or
  failing permanently (a non-retryable 4xx) propagates as
  ``TimesjobsFetchError``: without the discovery cursor there is nothing
  to show for the run.
* A **detail GET** failing after retries is logged and that single job is
  skipped, never aborting the batch -- one flaky detail must not discard
  the rest of the run.
* A non-JSON or non-object listing envelope propagates as a fetch error
  too (shape change / bot wall -- a fully broken site fails loudly).
* An envelope without a usable ``jobs`` list, an empty first page (past
  ``start_page`` or a block page), or rows that all fail token
  construction raise ``TimesjobsResponseError`` -- never a silent
  zero-jobs no-op.
"""

from __future__ import annotations

import json
import time
import urllib.parse

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import TimesjobsSettings
from .exceptions import TimesjobsFetchError, TimesjobsResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: The marker that separates a listing row's public slug from its opaque
#: detail token, e.g.
#: ``.../jobid-yH07ARBaH5dzpSvf+uAgZw==&source=srp``.
_JOBID_MARKER = "jobid-"


def detail_token(job_detail_url: str | None) -> str | None:
    """The URL-encoded detail token embedded in a listing ``jobDetailUrl``.

    Returns everything after ``jobid-`` (including a trailing
    ``&source=srp``), quoted as a single path segment, or None when the
    URL is missing or carries no marker. Exposed for the parser/tests so
    the token rule lives in exactly one place.
    """
    if not job_detail_url or _JOBID_MARKER not in job_detail_url:
        return None
    raw_token = job_detail_url.split(_JOBID_MARKER, 1)[1]
    if not raw_token:
        return None
    return urllib.parse.quote(raw_token, safe="")


class TimesjobsClient:
    """Walks the open listing paginator and hydrates each row's detail."""

    def __init__(self, settings: TimesjobsSettings | None = None) -> None:
        self._settings = settings or TimesjobsSettings()
        # One keep-alive session: a default run is ~2 listing POSTs plus
        # one detail GET per job, so reusing the pool matters.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
                "Origin": self._settings.web_base_url,
                "Referer": f"{self._settings.web_base_url}/",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _request(self, method: str, url: str, *, body: dict | None, what: str) -> requests.Response:
        """Send one request with retries; classify failures into the shared taxonomy."""
        settings = self._settings

        def _do() -> requests.Response:
            try:
                response = self._session.request(
                    method,
                    url,
                    data=json.dumps(body) if body is not None else None,
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
            raise TimesjobsFetchError(
                f"Could not reach TimesJobs ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise TimesjobsFetchError(
                f"TimesJobs request failed permanently ({what}): {exc}"
            ) from exc

    # -- discovery -------------------------------------------------------
    def _post_listing_page(self, page: int) -> dict:
        """POST one listing page and return the paginator envelope."""
        body = {
            "keyword": self._settings.keyword,
            "location": self._settings.location,
            "experience": "",
            "page": str(page),
            "size": str(self._settings.page_size),
            "jobFunctions": [],
            "company": "",
            "industry": "",
            "functionAreaId": "",
            "jobFunction": "",
        }
        response = self._request(
            "POST", self._settings.list_url, body=body, what=f"listing page {page}"
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TimesjobsFetchError(
                f"TimesJobs listing page {page} returned non-JSON (payload "
                f"shape change or block?): {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise TimesjobsFetchError(
                f"TimesJobs listing page {page} returned a non-object JSON payload."
            )
        return payload

    def _select_rows(self) -> list[dict]:
        """Listing rows from ``start_page`` until the window fills or the cursor ends."""
        settings = self._settings
        limit = settings.max_jobs_per_run
        page = settings.start_page
        first_page = page
        selected: list[dict] = []
        seen: set[str] = set()

        while len(selected) < limit:
            payload = self._post_listing_page(page)
            rows = payload.get("jobs")
            if not isinstance(rows, list):
                raise TimesjobsResponseError(
                    "TimesJobs listing envelope has no usable jobs list (keys: "
                    f"{sorted(payload)}). The payload shape may have changed."
                )
            if not rows:
                break  # past the end of the cursor (empty jobs list)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("jobId") or "")
                if not row_id or row_id in seen:
                    continue
                seen.add(row_id)
                selected.append(row)
            page += 1
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "TimesJobs discovery selected {} unique listing rows (window {}, "
            "listing pages {}-{} read).",
            len(selected),
            limit,
            first_page,
            page - 1,
        )
        return selected

    # -- detail ----------------------------------------------------------
    def _fetch_detail(self, token: str) -> dict | None:
        """GET one detail record; None (logged) when the call fails.

        A single detail failure is a skipped job, not a failed run: the
        listing row still hydrates a partial record, but a detail that
        cannot be read is better dropped than guessed at.
        """
        url = self._settings.detail_url_template.format(token=token)
        try:
            response = self._request("GET", url, body=None, what=f"detail {token[:24]}")
        except TimesjobsFetchError as exc:
            logger.warning("Skipping TimesJobs detail {} (fetch failed): {}", token[:24], exc)
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Skipping TimesJobs detail {} (non-JSON response).", token[:24])
            return None
        if not isinstance(payload, dict):
            logger.warning("Skipping TimesJobs detail {} (non-object payload).", token[:24])
            return None
        return payload

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk the listing cursor and hydrate each row's detail.

        Returns:
            Raw records ``{"url": listing jobDetailUrl, "listing": the
            listing row dict, "detail": the detail dict or None}``.

        Raises:
            TimesjobsFetchError: If a listing page POST failed after
                exhausting retries or the endpoint stopped serving JSON
                objects.
            TimesjobsResponseError: If the first page returned zero rows
                (past ``start_page`` / format change / block), the
                envelope lost its ``jobs`` list, or every selected row
                lacked a detail token.
        """
        rows = self._select_rows()
        if not rows:
            raise TimesjobsResponseError(
                "TimesJobs listing returned zero rows on page "
                f"{self._settings.start_page}. The listing format may have "
                "changed, the site may be unreachable, or start_page is "
                "past the end of the cursor."
            )

        jobs: list[dict] = []
        for index, row in enumerate(rows):
            job_detail_url = row.get("jobDetailUrl")
            token = detail_token(job_detail_url if isinstance(job_detail_url, str) else None)
            if token is None:
                logger.warning(
                    "Skipping TimesJobs listing row {}: no usable jobDetailUrl/token.",
                    row.get("jobId", f"<index {index}>"),
                )
                continue
            detail = self._fetch_detail(token)
            jobs.append({"url": job_detail_url, "listing": row, "detail": detail})
            if self._settings.fetch_delay_seconds and index + 1 < len(rows):
                time.sleep(self._settings.fetch_delay_seconds)

        if not jobs:
            raise TimesjobsResponseError(
                "TimesJobs returned zero usable job records across all "
                "selected rows (no detail token on any). The payload shape "
                "may have changed, or the responses were blocked/empty."
            )

        logger.info(
            "Fetched {} TimesJobs job records ({} rows selected, {} hydrated details).",
            len(jobs),
            len(rows),
            sum(1 for job in jobs if job["detail"] is not None),
        )
        return jobs

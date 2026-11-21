"""Fetches raw Bdjobs job records from its two keyless JSON endpoints.

This module's only responsibility: walk the open search paginator, then
hydrate each row from the open detail endpoint, and hand back raw
dictionaries. It does not validate individual job fields -- that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
* **Search** -- ``GET
  https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch`` with
  ``pg=N&rpp=100`` returns ``{message, statuscode, data[], premiumData[],
  common{total_records_found, totalpages, total_vacancies}}``. The
  ``data`` rows are the paginated feed (newest-first); ``premiumData``
  carries a small rotating set of promoted rows, so both arrays are merged
  and de-duplicated by ``Jobid``. Past the last page ``data`` is empty.
* **Detail** -- ``GET
  https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails`` with
  ``jobId=<id>&ln=1&IsCorporate=false`` returns ``{statuscode, message,
  data[{...}]}`` whose single object is the complete record.

Both URLs are the endpoints the site's own SPA calls (copied verbatim from
its bundled config chunk ``chunk-SMUS2CWI.js``). No key, cookie, token or
proxy: a browser ``User-Agent`` is enough.

robots.txt posture
------------------
The HTML hosts ``bdjobs.com`` and ``jobs.bdjobs.com`` both combine a
``User-agent: *`` group ending in ``Disallow: /``, so neither is fetched.
The API host answers HTTP 404 for ``/robots.txt`` (no policy file), which
RFC 9309 treats as "unavailable" and permits access -- see ``config.py``
for the full reading and the ``llv_li`` precedent. Only ``api.bdjobs.com``
is ever requested.

Failure taxonomy, mirroring the TimesJobs client:

* A **search page GET** failing after retries (transient exhaustion) or
  failing permanently (a non-retryable 4xx) propagates as
  ``BdjobsFetchError``: without the discovery feed there is nothing to
  show for the run.
* A **detail GET** failing after retries is logged and that single job is
  skipped, never aborting the batch -- one flaky detail must not discard
  the rest of the run.
* A non-JSON or non-object search envelope, or an envelope without a
  usable ``data`` list, propagates as a response error (shape change /
  bot wall -- a fully broken site fails loudly).
* An empty first page (a block page or a wrong endpoint) raises
  ``BdjobsResponseError`` -- never a silent zero-jobs no-op.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import BdjobsSettings
from .exceptions import BdjobsFetchError, BdjobsResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class BdjobsClient:
    """Walks the open search paginator and hydrates each row's detail."""

    def __init__(self, settings: BdjobsSettings | None = None) -> None:
        self._settings = settings or BdjobsSettings()
        # One keep-alive session: a default run is ~2 search GETs plus one
        # detail GET per job, so reusing the pool matters.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> BdjobsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- one retried request -------------------------------------------
    def _get(self, url: str, *, params: dict[str, Any], what: str) -> requests.Response:
        """Send one GET with retries; classify failures into the shared taxonomy."""

        def _do() -> requests.Response:
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._settings.request_timeout_seconds,
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
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise BdjobsFetchError(
                f"Could not reach Bdjobs ({what}) after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise BdjobsFetchError(f"Bdjobs request failed permanently ({what}): {exc}") from exc

    # -- discovery -------------------------------------------------------
    def _search_page(self, page: int) -> tuple[list[dict], int | None]:
        """GET one search page, returning ``(rows, total_pages)``.

        ``rows`` merges ``data`` and ``premiumData`` (first-seen order).
        """
        response = self._get(
            self._settings.search_url,
            params={"pg": page, "rpp": self._settings.rows_per_page},
            what=f"search page {page}",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise BdjobsResponseError(
                f"Bdjobs search page {page} returned non-JSON (payload shape change "
                f"or block?): {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise BdjobsResponseError(
                f"Bdjobs search page {page} returned a non-object JSON payload."
            )

        data = payload.get("data")
        if not isinstance(data, list):
            raise BdjobsResponseError(
                "Bdjobs search envelope has no usable data list (keys: "
                f"{sorted(payload)}). The payload shape may have changed."
            )

        rows: list[dict] = []
        for source in (data, payload.get("premiumData")):
            if isinstance(source, list):
                rows.extend(row for row in source if isinstance(row, dict))

        total_pages = None
        common = payload.get("common")
        if isinstance(common, dict):
            raw_total = common.get("totalpages")
            try:
                total_pages = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total_pages = None
        return rows, total_pages

    def _select_rows(self) -> list[dict]:
        """Search rows from page 1 until the window fills or the feed ends."""
        settings = self._settings
        limit = settings.max_jobs_per_run
        page = 1
        selected: list[dict] = []
        seen: set[str] = set()
        total_pages: int | None = None

        while len(selected) < limit and page <= settings.max_pages:
            rows, reported = self._search_page(page)
            if page == 1:
                if not rows:
                    raise BdjobsResponseError(
                        "Bdjobs search returned zero rows on page 1. The feed format "
                        "may have changed, the site may be unreachable, or the "
                        "endpoint moved."
                    )
                total_pages = reported
            elif not rows:
                break  # past the end of the feed

            for row in rows:
                row_id = str(row.get("Jobid") or "")
                if not row_id or row_id in seen:
                    continue
                seen.add(row_id)
                selected.append(row)

            if total_pages is not None and page >= total_pages:
                break
            page += 1
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "Bdjobs discovery selected {} unique rows (window {}, pages read {}).",
            len(selected),
            limit,
            page,
        )
        return selected

    # -- detail ----------------------------------------------------------
    def _fetch_detail(self, job_id: str) -> dict | None:
        """GET one detail record; None (logged) when the call fails.

        A single detail failure is a skipped job, not a failed run: the
        search row still hydrates a partial record, but a detail that
        cannot be read is better dropped than guessed at.
        """
        try:
            response = self._get(
                self._settings.detail_url,
                params={"jobId": job_id, "ln": 1, "IsCorporate": "false"},
                what=f"detail {job_id}",
            )
        except BdjobsFetchError as exc:
            logger.warning("Skipping Bdjobs detail {} (fetch failed): {}", job_id, exc)
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Skipping Bdjobs detail {} (non-JSON response).", job_id)
            return None
        if not isinstance(payload, dict):
            logger.warning("Skipping Bdjobs detail {} (non-object payload).", job_id)
            return None
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        logger.warning("Skipping Bdjobs detail {} (empty data list).", job_id)
        return None

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk the search feed and hydrate each row's detail.

        Returns:
            Raw records ``{"id": Jobid, "listing": the search row dict,
            "detail": the detail dict or None, "url": the public detail
            page URL}``.

        Raises:
            BdjobsFetchError: If a search page GET failed after exhausting
                retries or a permanent 4xx was returned.
            BdjobsResponseError: If the first page returned zero rows or
                the envelope lost its ``data`` list.
        """
        rows = self._select_rows()

        jobs: list[dict] = []
        for index, row in enumerate(rows):
            job_id = str(row.get("Jobid") or "")
            if not job_id:
                logger.warning("Skipping Bdjobs search row {}: no Jobid.", index)
                continue
            detail = self._fetch_detail(job_id)
            jobs.append(
                {
                    "id": job_id,
                    "listing": row,
                    "detail": detail,
                    "url": f"{self._settings.detail_page_base}{job_id}",
                }
            )
            if self._settings.fetch_delay_seconds and index + 1 < len(rows):
                time.sleep(self._settings.fetch_delay_seconds)

        logger.info(
            "Fetched {} Bdjobs job records ({} hydrated details).",
            len(jobs),
            sum(1 for job in jobs if job["detail"] is not None),
        )
        return jobs

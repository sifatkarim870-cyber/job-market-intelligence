"""Fetches raw job data from Irantalent.

This module's only responsibility: walk the open POST search endpoint
and hand back raw dictionaries. It does not validate individual job
fields — that is ``parser.py``'s job. Same fetch/validate/decide
separation the other scrapers establish.

Where the data lives (confirmed live, 2026-10-07, probes r1-r10)
----------------------------------------------------------------
IranTalent needs only ONE request per job because discovery and data
are the same call:

* **``POST https://api.irantalent.com/api/v1/employer/position/search``
  with body ``{"page": N}``** returns a Laravel paginator envelope
  ``{current_page, data, total, last_page, …}`` where ``data`` holds
  up to 30 COMPLETE job rows (title pair, HTML ``role_description``,
  salary bounds in whole Toman, ``employment_type``, ``employer``,
  ``job_category``, ``lived_at``). No auth, no cookie, no Referer —
  a bare UA + JSON content-type answered 200 on every probe. The
  site's own pages are 4.4 KB SPA shells with no embedded data, so
  this endpoint is the only sane path (sitemaps list categories, not
  jobs — see ``irantalent_recon_notes``).
* **Pagination is a stable newest-first cursor**: rows descend by
  ``lived_at``/id across pages (page 1 = yesterday's postings,
  page 63 = the oldest live jobs), ``per_page`` is fixed at 30 (the
  ``size`` body param is ignored — verified), and past the end the API
  answers HTTP 200 with ``data: []`` (verified at page 64). No
  skip-known exclusion is needed or possible here: capped CI runs read
  the head of the cursor (the newest window, like Jobinja) and a local
  backfill raises ``max_jobs_per_run`` to sweep the whole ~1,872-job
  live corpus; content-hash dedup absorbs the overlap.

Failure taxonomy, mirroring the Jobvision client (simplified — every
page IS the data, so there is no per-job fetch to skip):

* A **page POST** failing after retries (transient exhaustion) or
  failing permanently (4xx) propagates as ``IrantalentFetchError``:
  without that page there is nothing to show for the run.
* A non-JSON or non-object envelope propagates as a fetch error too
  (shape change / bot wall — a fully broken site fails loudly).
* A paginator envelope without a usable ``data`` list, an empty first
  page (past ``start_page`` or a block page), or rows that all fail
  URL construction raise ``IrantalentResponseError`` — never a silent
  zero-jobs no-op.
"""

from __future__ import annotations

import json
import time

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import IrantalentSettings
from .exceptions import IrantalentFetchError, IrantalentResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class IrantalentClient:
    """Walks the open search paginator and returns raw job rows."""

    def __init__(self, settings: IrantalentSettings | None = None) -> None:
        self._settings = settings or IrantalentSettings()
        # One keep-alive session: even the full-corpus sweep is only
        # ~63 page POSTs, but a fresh TCP+TLS handshake each would
        # triple the wall time.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _post(self, body: dict, *, what: str) -> requests.Response:
        """POST one JSON body with retries; classify failures into the shared taxonomy."""
        settings = self._settings

        def _do() -> requests.Response:
            try:
                response = self._session.post(
                    settings.api_search_url,
                    data=json.dumps(body),
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
            raise IrantalentFetchError(
                f"Could not reach IranTalent ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise IrantalentFetchError(
                f"IranTalent request failed permanently ({what}): {exc}"
            ) from exc

    def _post_page(self, page: int) -> dict:
        """POST one search page and return the paginator envelope.

        A non-JSON answer is a shape change (or a bot wall) affecting
        every request to the endpoint — it raises instead of being
        skippable, so a broken site fails loudly.
        """
        response = self._post({"page": page}, what=f"search page {page}")
        try:
            body = response.json()
        except ValueError as exc:
            raise IrantalentFetchError(
                f"IranTalent search page {page} returned non-JSON (payload "
                f"shape change or block?): {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise IrantalentFetchError(
                f"IranTalent search page {page} returned a non-object JSON payload."
            )
        return body

    # -- discovery -------------------------------------------------------
    def _select_rows(self) -> list[dict]:
        """Job rows from ``start_page`` until the window fills or the cursor ends.

        Returns:
            Up to ``max_jobs_per_run`` row dicts in date-descending
            order (first occurrence wins — ids repeating across a page
            boundary collapse, keeping the window honest).
        """
        settings = self._settings
        limit = settings.max_jobs_per_run
        page = settings.start_page
        first_page = page
        selected: list[dict] = []
        seen: set[object] = set()

        while len(selected) < limit:
            body = self._post_page(page)
            data = body.get("data")
            if not isinstance(data, list):
                raise IrantalentResponseError(
                    "IranTalent search envelope has no usable data list (keys: "
                    f"{sorted(body)}). The payload shape may have changed."
                )
            if not data:
                break  # past the end of the cursor (empty data list)
            for row in data:
                if not isinstance(row, dict):
                    continue
                row_id = row.get("id")
                if row_id is None or row_id in seen:
                    continue
                seen.add(row_id)
                selected.append(row)
            page += 1
            # Pace page reads like every other source's fetch loop
            # (Jobinja's unpaced burst tripped its WAF the same morning).
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "Irantalent discovery selected {} unique job rows (window {}, "
            "search pages {}-{} read).",
            len(selected),
            limit,
            first_page,
            page - 1,
        )
        return selected

    # -- record building --------------------------------------------------
    def _job_url(self, row: dict) -> str | None:
        """``/{en|fa}/job/{slug}/{id}`` from the row's own identity fields.

        The locale follows the row's ``language`` (both prefixes answer
        200 either way — the SPA routes by id and treats the slug as
        cosmetic; verified live). ``None`` when id/slug are missing —
        the parser contract treats that as an unusable row.
        """
        row_id = row.get("id")
        slug = row.get("slug")
        if not row_id or not slug:
            return None
        locale = "en" if row.get("language") == "en" else "fa"
        return f"{self._settings.web_base_url}/{locale}/job/{slug}/{row_id}"

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk the search cursor and return raw job records.

        Returns:
            Raw records ``{"url": constructed job URL, "payload": the
            complete search row dict}``.

        Raises:
            IrantalentFetchError: If a page POST failed after exhausting
                retries or the endpoint stopped serving JSON objects.
            IrantalentResponseError: If the first page returned zero
                rows (past ``start_page`` / format change / block), the
                envelope lost its ``data`` list, or every selected row
                failed URL construction.
        """
        rows = self._select_rows()
        if not rows:
            raise IrantalentResponseError(
                "IranTalent search returned zero job rows on page "
                f"{self._settings.start_page}. The listing format may have "
                "changed, the site may be unreachable, or start_page is "
                "past the end of the cursor."
            )

        jobs: list[dict] = []
        for row in rows:
            url = self._job_url(row)
            if url is None:
                logger.warning(
                    "Skipping Irantalent row {}: missing id/slug (unusable identity).",
                    row.get("id", "<none>"),
                )
                continue
            jobs.append({"url": url, "payload": row})

        if not jobs:
            raise IrantalentResponseError(
                "IranTalent returned zero usable job records across all "
                "selected rows (no id/slug on any). The payload shape may "
                "have changed, or the responses were blocked/empty."
            )

        logger.info(
            "Fetched {} Irantalent job records ({} rows selected).",
            len(jobs),
            len(rows),
        )
        return jobs

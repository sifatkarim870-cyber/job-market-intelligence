"""Fetches raw postings from USAJOBS, the US federal job board.

Two endpoints, because USAJOBS has no single call that returns a posting:

  1. ``GET /api/search`` -- keyword search returning 50-500 postings per request,
     each with the structured descriptor (organisation, salary, grade,
     location with coordinates, dates).
  2. ``GET {PositionURI}`` -- the public job page, whose schema.org JSON-LD
     carries the description, qualifications and education requirements.

There is no position detail endpoint; ``/api/v2/position/{id}`` and four other
spellings all return 404. The API's own ``PositionFormattedDescription`` is a
marker object, not text. So step 2 is the only route to a real description.

Rate limit: data.gov meters keys at 500 requests/hour. One search page plus one
job page per result is ~51 requests, so :mod:`config` sets a 1s floor between
requests to keep a full keyword inside the hourly budget rather than earning a
403 partway through.
"""

from __future__ import annotations

import time

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
    fetch_json,
)
from job_market_intel.common.retry import call_with_retry

from .config import USAJobsSettings
from .exceptions import (
    USAJobsAuthError,
    USAJobsFetchError,
    USAJobsResponseError,
)

#: Guard on the envelope. The old v1 shape put fields at the top level; v2
#: nests each result under MatchedObjectDescriptor. ``fetch_page`` therefore
#: requires both levels to be present rather than accepting either shape --
#: being permissive here is what would let a silent API change look like
#: "zero results" on every future run.


class USAJobsClient:
    """Fetches postings from the USAJOBS federal API and public job pages."""

    def __init__(self, settings: USAJobsSettings | None = None) -> None:
        self._settings = settings or USAJobsSettings()

    # ------------------------------------------------------------------ auth

    def _headers(self, host: str | None = None) -> dict[str, str]:
        key = self._settings.api_key
        if not key:
            raise USAJobsAuthError(
                "no USAJOBS API key configured. Set USAJOBS_API_KEY, or point "
                "USAJOBS_API_KEY_FILE at a file containing it. Free keys come "
                "from https://developer.usajobs.gov/."
            )
        headers = {
            "Authorization-Key": key,
            "User-Agent": self._settings.user_agent,
            "Accept": "application/json",
        }
        if host:
            headers["Host"] = host
        return headers

    # ----------------------------------------------------------------- fetch

    def _get_json(self, url: str, host: str | None = None) -> dict:
        try:
            return call_with_retry(
                fetch_json,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=float(self._settings.request_timeout_seconds),
                user_agent=self._settings.user_agent,
                extra_headers={k: v for k, v in self._headers(host).items() if k != "User-Agent"},
            )
        except TransientHTTPError as exc:
            raise USAJobsFetchError(
                f"USAJOBS unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            if "401" in str(exc) or "403" in str(exc):
                raise USAJobsAuthError(
                    f"USAJOBS rejected the API key ({exc}). Check the value and "
                    f"the key's hourly request budget."
                ) from exc
            raise USAJobsFetchError(f"USAJOBS refused {url}: {exc}") from exc

    def search_url(self, keyword: str, page: int = 1) -> str:
        """URL for one page of keyword results."""
        from urllib.parse import quote_plus

        return (
            f"{self._settings.api_base_url}{self._settings.search_path}"
            f"?Keyword={quote_plus(keyword)}"
            f"&ResultsPerPage={self._settings.results_per_page}&Page={page}"
        )

    def fetch_page(self, keyword: str, page: int = 1) -> tuple[list[dict], int]:
        """Return (descriptors, total_available) for one page of a keyword.

        ``total_available`` is ``SearchResultCountAll`` -- how many postings
        the keyword matches in total, which is what tells us whether the
        configured page budget is seeing everything or only a prefix.
        """
        payload = self._get_json(self.search_url(keyword, page), host="data.usajobs.gov")
        result = payload.get("SearchResult")
        if not isinstance(result, dict):
            raise USAJobsResponseError(
                "USAJOBS search response has no SearchResult object; keys were "
                f"{sorted(payload.keys())[:8]}. The response envelope has changed."
            )
        items = result.get("SearchResultItems")
        if not isinstance(items, list):
            raise USAJobsResponseError(
                "USAJOBS search response has no SearchResultItems list; keys were "
                f"{sorted(result.keys())[:8]}. The response envelope has changed."
            )
        descriptors = [i.get("MatchedObjectDescriptor", {}) for i in items if isinstance(i, dict)]
        total = result.get("SearchResultCountAll") or result.get("SearchResultCount") or 0
        logger.info(
            "usajobs keyword={!r} page={}: {} item(s) of {} total",
            keyword,
            page,
            len(descriptors),
            total,
        )
        return descriptors, int(total)

    def fetch_job_page(self, url: str) -> str:
        """Fetch a posting's public job page HTML (for the JSON-LD block).

        Uses ``fetch_html`` rather than ``fetch_json``: the page is HTML, and the
        JSON-LD block inside it is extracted by the parser.
        """
        try:
            return call_with_retry(
                fetch_html,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=float(self._settings.request_timeout_seconds),
                user_agent=self._settings.user_agent,
            )
        except TransientHTTPError as exc:
            raise USAJobsFetchError(f"USAJOBS job page unreachable: {exc}") from exc
        except PermanentHTTPError as exc:
            raise USAJobsFetchError(f"USAJOBS job page refused {url}: {exc}") from exc

    def _fetch_page_html(self, descriptor: dict) -> tuple[str | None, str]:
        """Fetch one posting's job page, returning ``(html, error_message)``."""
        uri = (descriptor.get("PositionURI") or "").replace(":443", "")
        if not self._settings.fetch_job_pages or not uri:
            return None, ""
        try:
            html = self.fetch_job_page(uri)
        except USAJobsFetchError as exc:
            return None, str(exc)
        time.sleep(self._settings.inter_request_delay_seconds)
        return html, ""

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Walk every keyword, returning raw posting dictionaries.

        Returns ``(records, failures)``; callers log failures rather than
        aborting, since one posting or one keyword failing must not cost a run.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        seen: set[str] = set()
        records: list[dict] = []
        failures: dict[str, str] = {}

        for keyword in self._settings.default_keywords:
            if len(records) >= budget:
                logger.info("usajobs: job budget of {} reached, stopping", budget)
                break
            try:
                descriptors, _total = self.fetch_page(keyword, 1)
            except (USAJobsFetchError, USAJobsResponseError, USAJobsAuthError) as exc:
                failures[f"keyword:{keyword}"] = str(exc)
                logger.warning("usajobs keyword {!r} failed: {}", keyword, exc)
                if isinstance(exc, USAJobsAuthError):
                    break  # a bad key will not fix itself; stop burning requests
                continue

            for descriptor in descriptors:
                position_id = descriptor.get("PositionID")
                if not position_id or position_id in seen or len(records) >= budget:
                    continue
                seen.add(position_id)
                html, page_error = self._fetch_page_html(descriptor)
                if page_error:
                    failures[position_id] = page_error
                    logger.warning("usajobs job page {} failed: {}", position_id, page_error)
                records.append(
                    {
                        "descriptor": descriptor,
                        "html": html,
                        "search_keyword": keyword,
                        "url": (descriptor.get("PositionURI") or "").replace(":443", "") or None,
                    }
                )

        if not records and not failures:
            raise USAJobsResponseError(
                f"no postings returned across {len(self._settings.default_keywords)} "
                "keywords. Either the keyword list is stale or the API response "
                "shape changed -- raised rather than returning empty so the two "
                "cannot be confused."
            )
        return records, failures

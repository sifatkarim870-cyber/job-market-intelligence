"""Fetches raw job data from JobMaster.

This module's only responsibility: discover candidate job ids by
walking the anonymous filter-cell space on ``/jobs/``, fetch each
job's detail page, and hand back raw ``{"url", "html"}`` dictionaries.
Parsing/validation of a page's content is ``parser.py``'s job — same
fetch/validate/decide separation the other scrapers establish.

Where the data lives (confirmed live, 2026-10-07)
---------------------------------------------------
JobMaster has no usable public JSON feed. The discovery machinery is:

* **Facet dictionary** — ``GET https://api.il.jobmaster.co.il/api/
  check/groupBy/list/?q={he-letter}`` returns JSON lists of main
  categories (``headcatnumFilter``) and employment-type chips
  (``jobtypeFilter``). Used only to enumerate the search-cell space.
* **Discovery — ``GET /jobs/?headcatnum=N`` and
  ``GET /jobs/?headcatnum=N&jobtype=M``.** All results pages are
  server-rendered with up to 10 newest cards as ``<article
  id="misra<ID>">``; the total lives in ``#desktopResultsHeader``
  ("נמצאו 96 משרות"). Any cell's deeper pages (``currPage``) are
  login-walled, so each anonymous hit yields at most one card page of
  10 jobs — the client compensates by probing many cells (budget
  bounded by ``max_discovery_requests``) and de-duplicating ids.
* **Detail — ``GET /jobs/checknum.asp?key={id}``** renders the full
  job record server-side (``article__jobHead`` + ``article__jobBody``)
  as plain HTML (no JSON-LD).

No auth, no cookies, no signing — plain GETs with a browser-style
User-Agent. ``common/http_client.py`` is GET-only with no listing/page
parsing, so this client does its own request loop while reusing the
shared error taxonomy (``TransientHTTPError``/``PermanentHTTPError``)
and ``call_with_retry``.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import JobmasterSettings
from .exceptions import JobmasterFetchError, JobmasterResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_IDS_RE = re.compile(r'<article id="misra(\d+)"')
_TOTAL_RE = re.compile(r'id="desktopResultsHeader"[^>]*>\s*([^<]+)')
_COUNTED_RE = re.compile(r"(\d[\d,]*)")
_MAX_UNEXPECTED_CELL_ERRORS = 20


class _Census:
    """Mutable counters for one discovery walk.

    Lives outside the loop as a small object so the walk itself stays
    readable — the probed/visited bookkeeping (probes, errors,
    overflow cells) would otherwise be seven non-branching moves
    interleaved with the nested-loop logic.
    """

    def __init__(self) -> None:
        self.candidates: dict[str, int | None] = {}
        self.probes = 0
        self.errors = 0
        self.overflow_cells = 0


def _visit(client: JobmasterClient, census: _Census, path: str, what: str) -> None:
    census.probes += 1
    try:
        ids, total = client._probe(path, what=what)
    except JobmasterFetchError as exc:
        census.errors += 1
        logger.warning("Discovery probe {} failed: {}", path, exc)
        if census.errors >= _MAX_UNEXPECTED_CELL_ERRORS:
            raise
        return
    if total is not None and total > 10:
        census.overflow_cells += 1
    for jid in ids:
        census.candidates.setdefault(jid, total)


class JobmasterClient:
    """Anonymous-only JobMaster detail fetcher (see module docstring)."""

    def __init__(self, settings: JobmasterSettings | None = None) -> None:
        self._settings = settings or JobmasterSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _request_text(self, url: str, *, what: str) -> str:
        """GET one URL with retries; return the response body as text."""
        settings = self._settings

        def _do() -> str:
            try:
                response = self._session.get(url, timeout=settings.request_timeout_seconds)
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientHTTPError(str(exc)) from exc
            except requests.RequestException as exc:
                raise PermanentHTTPError(str(exc)) from exc

            if response.status_code in _RETRYABLE_STATUS:
                raise TransientHTTPError(f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise PermanentHTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            if "account.jobmaster.co.il" in str(response.url):
                # Anonymous pagination (currPage) redirects into the
                # login wall; our discovery paths should never do that.
                raise PermanentHTTPError(
                    f"Redirected to the account login gate ({response.url[:160]}) for {what}."
                )
            return response.text

        try:
            return call_with_retry(
                _do,
                retry_exception_types=TransientHTTPError,
                max_attempts=settings.max_retry_attempts,
                initial_wait_seconds=settings.retry_initial_wait_seconds,
                max_wait_seconds=settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise JobmasterFetchError(
                f"Could not reach JobMaster ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobmasterFetchError(
                f"JobMaster request failed permanently ({what}): {exc}"
            ) from exc

    # -- discovery ------------------------------------------------------
    def _facets(self) -> tuple[list[dict], list[dict]]:
        """Headcatnum/jobtype facet lists from the open groupBy API."""
        url = (
            f"{self._settings.api_base_url}/api/check/groupBy/list/"
            f"?q={quote(self._settings.discovery_seed_query)}"
        )
        text = self._request_text(url, what="groupBy facets")
        try:
            body = json.loads(text)
        except ValueError as exc:
            raise JobmasterResponseError(
                f"groupBy facets answer was not JSON (len={len(text)})."
            ) from exc
        heads = body.get("headcatnumFilter")
        types = body.get("jobtypeFilter")
        if not isinstance(heads, list) or not isinstance(types, list) or not heads:
            raise JobmasterResponseError(
                f"groupBy facets payload lost its headcat/jobtype lists (keys: {sorted(body)})."
            )
        return heads, types

    def _probe(self, path: str, *, what: str) -> tuple[list[str], int | None]:
        """One listing-cell GET -> (card ids, advertised total or None)."""
        text = self._request_text(f"{self._settings.web_base_url}{path}", what=what)
        ids = _IDS_RE.findall(text)
        total: int | None = None
        m = _TOTAL_RE.search(text)
        if m:
            digits = _COUNTED_RE.search(m.group(1))
            if digits:
                try:
                    total = int(digits.group(1).replace(",", ""))
                except ValueError:
                    total = None
        return ids, total

    def _collect_candidates(self) -> dict[str, int | None]:
        """Walk the anonymous filter-cell space, returning candidate ids.

        Each probe of a listing cell contributes up to its 10 newest
        cards. The same job can appear in many cells, so ids are
        deduplicated in first-seen order. Discovery probe count is
        capped at ``max_discovery_requests``; detail fetching is a
        second, smaller cap.
        """
        settings = self._settings
        heads, types = self._facets()
        census = _Census()
        cap = settings.max_discovery_requests

        # Phase 1 — one unfiltered probe per head category.
        for head in heads:
            if census.probes >= cap:
                break
            num = head.get("num")
            if num is not None:
                _visit(self, census, f"/jobs/?headcatnum={num}", f"headcat {num} general")

        # Phase 2 — employment-type descent (FT chips dominate the corpus).
        pairs = (
            (head.get("num"), typ.get("num"))
            for head in heads
            for typ in types
        )
        for num, tnum in pairs:
            if census.probes >= cap:
                break
            if num is None or tnum is None:
                continue
            _visit(
                self,
                census,
                f"/jobs/?headcatnum={num}&jobtype={tnum}",
                f"headcat {num} jobtype {tnum}",
            )

        logger.info(
            "JobMaster discovery: {} probes, {} unique candidate ids, "
            "{} cells >10 (newest-10 only), {} probe errors.",
            census.probes,
            len(census.candidates),
            census.overflow_cells,
            census.errors,
        )
        return census.candidates

    def fetch_raw_jobs(self, *, exclude_ids: set[str] | None = None) -> list[dict]:
        """Discover candidates and fetch their detail pages.

        Returns:
            Raw records ``{"url": canonical detail URL, "html": detail
            page HTML}`` for up to ``max_jobs_per_run`` unseen ids.

        Raises:
            JobmasterFetchError/JobmasterResponseError on broken
            discovery (every probe failing or zero candidates).
        """
        candidates = self._collect_candidates()
        if not candidates:
            raise JobmasterResponseError(
                "Discovery produced zero candidate ids; the cell-space layout may have changed."
            )

        unknown = exclude_ids or set()
        detail_ids = [jid for jid in candidates if jid not in unknown]
        detail_ids = detail_ids[: self._settings.max_jobs_per_run]
        logger.info(
            "Fetching details for {} unseen ids (candidates={}, known={}).",
            len(detail_ids),
            len(candidates),
            len(unknown),
        )

        jobs: list[dict] = []
        for jid in detail_ids:
            url = f"{self._settings.web_base_url}/jobs/checknum.asp?key={jid}"
            try:
                html = self._request_text(url, what=f"detail {jid}")
            except JobmasterFetchError as exc:
                logger.warning("Skipping detail {}: {}", jid, exc)
                continue
            jobs.append({"url": url, "html": html})
            if self._settings.fetch_delay_seconds:
                time.sleep(self._settings.fetch_delay_seconds)

        if not jobs:
            raise JobmasterResponseError(
                "No detail pages could be fetched for the selected candidates."
            )
        return jobs

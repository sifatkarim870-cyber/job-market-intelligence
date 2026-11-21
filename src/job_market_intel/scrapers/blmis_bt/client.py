"""Fetches raw BLMIS vacancy records from its public jobseeker page.

This module's only responsibility: make the single public GET, pull the
Livewire ``wire:initial-data`` JSON blob out of the HTML, merge the six
``job_by_*`` facet arrays into one de-duplicated list and hand back raw
dictionaries. It does not validate individual job fields -- that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
``GET https://www.blmis.gov.bt/jobseeker_page/mispage`` is a Laravel
Livewire page that renders the current vacancy inventory into the
component's ``wire:initial-data`` attribute (an HTML-entity-encoded JSON
blob) *before* any JavaScript runs, so a plain HTTP GET is the whole
source. ``serverMemo.data`` carries six overlapping browse facets --
``job_by_categories``, ``job_by_location``, ``job_by_company``,
``job_by_qualification``, ``job_by_yelp`` and ``job_by_oversea`` -- whose
union was 442 unique ``application_no`` values at scoping. They are
merged and de-duplicated by ``application_no``.

No key, cookie, token, login, proxy or browser: a browser ``User-Agent``
is enough.

robots.txt posture
------------------
``https://www.blmis.gov.bt/robots.txt`` (HTTP 200) is a bare
``User-agent: *`` group with an EMPTY ``Disallow`` (allow-all). Nothing
here is disallowed, and the run makes a single GET regardless. TLS
verification stays on.

Failure taxonomy, mirroring the Bdjobs/TimesJobs clients:

* A **listing GET** failing after retries (transient exhaustion) or
  failing permanently (a non-retryable 4xx) propagates as
  ``BlmisFetchError``: without that response there is nothing to show for
  the run.
* A page with **no ``wire:initial-data`` attribute**, a non-JSON blob, or
  a JSON envelope without ``serverMemo.data`` propagates as a response
  error (format change / block page -- a fully broken site fails loudly).
* A first read yielding **zero unique vacancies** raises
  ``BlmisResponseError`` -- never a silent zero-jobs no-op.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import BlmisSettings
from .exceptions import BlmisFetchError, BlmisResponseError
from .models import OVERSEA_VACANCY_TYPE_ID

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Pull the Livewire component blob out of the page. The attribute value is
#: HTML-entity-encoded (``&quot;`` etc.) and never contains a raw ``"``, so a
#: non-greedy quoted capture is exact.
_INITIAL_DATA_RE = re.compile(r'wire:initial-data="([^"]*)"')

#: The six facet arrays that hold vacancies; anything else in
#: ``serverMemo.data`` (training lists, lookup dropdowns) is ignored.
_JOB_ARRAY_KEYS = (
    "job_by_categories",
    "job_by_location",
    "job_by_company",
    "job_by_qualification",
    "job_by_yelp",
    "job_by_oversea",
)


class BlmisClient:
    """Fetches the jobseeker page and extracts its embedded vacancy records."""

    def __init__(self, settings: BlmisSettings | None = None) -> None:
        self._settings = settings or BlmisSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> BlmisClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- one retried request -------------------------------------------
    def _get(self, url: str, *, what: str) -> requests.Response:
        """Send one GET with retries; classify failures into the shared taxonomy."""

        def _do() -> requests.Response:
            try:
                response = self._session.get(
                    url,
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
            raise BlmisFetchError(
                f"Could not reach BLMIS ({what}) after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise BlmisFetchError(f"BLMIS request failed permanently ({what}): {exc}") from exc

    # -- extraction ------------------------------------------------------
    @staticmethod
    def _decode_initial_data(page_html: str) -> dict:
        """Return the parsed ``wire:initial-data`` JSON object for the page."""
        match = _INITIAL_DATA_RE.search(page_html)
        if match is None:
            raise BlmisResponseError(
                "BLMIS page carries no wire:initial-data attribute (payload "
                "shape change or block page?)."
            )
        try:
            data = json.loads(html.unescape(match.group(1)))
        except ValueError as exc:
            raise BlmisResponseError(
                f"BLMIS wire:initial-data is not valid JSON (payload shape change or block?): {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise BlmisResponseError("BLMIS wire:initial-data is not a JSON object.")
        return data

    def _select_rows(self) -> list[tuple[str, dict, bool]]:
        """Return ``(application_no, record, is_oversea)`` for every vacancy.

        The six ``job_by_*`` facets overlap, so records are de-duplicated by
        ``application_no`` (first-seen order, which is the order the server
        rendered them). Overseas postings -- either the ``job_by_oversea``
        facet or ``vacancy_type_id`` 516 -- are flagged.
        """
        response = self._get(self._settings.list_url, what="jobseeker page")
        data = self._decode_initial_data(response.text)

        server_memo = data.get("serverMemo")
        if not isinstance(server_memo, dict):
            raise BlmisResponseError("BLMIS payload has no serverMemo object.")
        memo_data = server_memo.get("data")
        if not isinstance(memo_data, dict):
            raise BlmisResponseError("BLMIS payload has no serverMemo.data object.")

        selected: list[tuple[str, dict, bool]] = []
        seen: set[str] = set()
        for key in _JOB_ARRAY_KEYS:
            rows = memo_data.get(key)
            if not isinstance(rows, list):
                continue
            facet_oversea = key == "job_by_oversea"
            for row in rows:
                if not isinstance(row, dict):
                    continue
                job_id = str(row.get("application_no") or "").strip()
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)
                oversea = facet_oversea or row.get("vacancy_type_id") == OVERSEA_VACANCY_TYPE_ID
                selected.append((job_id, row, bool(oversea)))

        selected = selected[: self._settings.max_jobs_per_run]
        logger.info(
            "BLMIS discovery selected {} unique vacancies across {} facets (cap {}).",
            len(selected),
            len(_JOB_ARRAY_KEYS),
            self._settings.max_jobs_per_run,
        )
        return selected

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch and return every raw BLMIS vacancy record.

        Returns:
            Raw records ``{"id": application_no, "record": the vacancy dict,
            "oversea": bool, "url": the public detail page URL}``.

        Raises:
            BlmisFetchError: If the listing GET failed after exhausting
                retries or a permanent 4xx was returned.
            BlmisResponseError: If the page had no usable Livewire blob or
                yielded zero vacancies.
        """
        rows = self._select_rows()
        if not rows:
            raise BlmisResponseError(
                "BLMIS jobseeker page yielded zero vacancies. The feed format "
                "may have changed, the site may be unreachable, or the page "
                "moved."
            )

        jobs: list[dict[str, Any]] = []
        for job_id, record, oversea in rows:
            jobs.append(
                {
                    "id": job_id,
                    "record": record,
                    "oversea": oversea,
                    "url": f"{self._settings.detail_page_base}{job_id}",
                }
            )

        logger.info(
            "Fetched {} BLMIS vacancy records ({} overseas).",
            len(jobs),
            sum(1 for job in jobs if job["oversea"]),
        )
        return jobs

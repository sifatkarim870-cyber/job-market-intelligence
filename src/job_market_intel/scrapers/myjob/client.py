"""Fetches raw job data from MyJob.mu.

This module's only responsibility: make the HTTP requests (with retries
for transient failures), page through the job-board JSON list endpoint,
optionally enrich each listed job with its detail payload, and hand back
raw dictionaries. It does not validate individual job fields — that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-10-05)
-------------------------------------------------
MyJob.mu (Mauritius) is a Nuxt frontend on www.myjob.mu backed by a JSON
API on app.myjob.mu. The frontend's runtime config
(``window.__NUXT__.config.public.baseApiUrl``) declares the API base as
``https://app.myjob.mu/api``, and its job-search page calls:

* **List** — ``GET /api/job-board/jobs?limit=20&sort=latest&page=N``
  returning a bare JSON array (no envelope). The server silently caps
  ``limit`` at 20: ``limit=1000`` still returns 20 items, and a page past
  the end returns ``[]`` rather than an error. ~1,500 active jobs span
  ~75 pages.
* **Detail** — ``GET /api/job-board/jobs/{id}`` returning the same object
  plus ``description`` (HTML) and ``workArrangement``. The list payload
  has no description at all, so descriptions require this second call
  (gated behind ``fetch_details``).

No auth, no cookies, no signing — both endpoints answer a plain GET with
``Accept: application/json``. The public job page
``https://www.myjob.mu/jobs/{slug}`` also works (HTTP 200) and is what
``original_url`` points humans at.
"""

from __future__ import annotations

import time

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_json
from job_market_intel.common.retry import call_with_retry

from .config import MyJobSettings
from .exceptions import MyJobFetchError, MyJobResponseError


class MyJobClient:
    """Fetches the current MyJob.mu job-board records."""

    def __init__(self, settings: MyJobSettings | None = None) -> None:
        self._settings = settings or MyJobSettings()

    def _get_json(self, url: str, *, what: str) -> object:
        try:
            return call_with_retry(
                fetch_json,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
            )
        except TransientHTTPError as exc:
            raise MyJobFetchError(
                f"Could not reach MyJob.mu ({what}) after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise MyJobFetchError(f"MyJob.mu request failed permanently ({what}): {exc}") from exc

    def _fetch_list_page(self, page: int) -> list[dict]:
        url = (
            f"{self._settings.api_base_url}"
            f"?limit={self._settings.page_size}&sort=latest&page={page}"
        )
        payload = self._get_json(url, what=f"list page {page}")
        if not isinstance(payload, list):
            raise MyJobResponseError(
                f"MyJob.mu list page {page} returned "
                f"{type(payload).__name__}, expected a JSON array. "
                "The API's response shape may have changed."
            )
        return [entry for entry in payload if isinstance(entry, dict)]

    def _fetch_detail(self, job_id: object) -> dict | None:
        """Fetch one job's detail payload; None if it can't be fetched.

        A missing detail only costs the description (the list entry still
        carries title/company/location/…), so detail failures are logged
        and skipped rather than failing the run — same philosophy as the
        parsers' skip-don't-crash behaviour.
        """
        url = f"{self._settings.api_base_url}/{job_id}"
        try:
            payload = self._get_json(url, what=f"detail {job_id}")
        except MyJobFetchError as exc:
            logger.warning("Skipping detail for MyJob.mu job {}: {}", job_id, exc)
            return None
        if not isinstance(payload, dict) or not payload.get("description"):
            logger.warning("MyJob.mu job {} detail had no usable payload.", job_id)
            return None
        return payload

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch up to ``max_pages_per_run`` list pages, then enrich.

        Returns:
            A list of raw job dictionaries in MyJob.mu's own field
            naming. Each list entry is merged with its detail payload
            (detail keys win) when ``fetch_details`` is on, so the
            records carry ``description``/``workArrangement``.

        Raises:
            MyJobFetchError: If a request failed after exhausting retries.
            MyJobResponseError: If a payload wasn't a usable job list.
        """
        listed: list[dict] = []
        for page in range(1, self._settings.max_pages_per_run + 1):
            logger.info("Fetching MyJob.mu list page {}.", page)
            page_jobs = self._fetch_list_page(page)
            logger.info("MyJob.mu page {}: {} jobs (total listed so far: {}).",
                        page, len(page_jobs), len(listed) + len(page_jobs))
            if not page_jobs:
                break
            listed.extend(page_jobs)

        if not listed:
            raise MyJobResponseError(
                "MyJob.mu returned zero recognizable job records across all "
                "fetched pages. The payload shape may have changed, or this "
                "may be an empty/blocked response."
            )

        if not self._settings.fetch_details:
            logger.info("Fetched {} MyJob.mu jobs (details disabled).", len(listed))
            return listed

        # De-duplicate by id first: pages are fetched newest-first, so a
        # job posted between two page requests can appear twice and would
        # otherwise cost a second detail round-trip.
        unique: dict[str, dict] = {}
        for entry in listed:
            unique.setdefault(str(entry.get("id")), entry)

        enriched: list[dict] = []
        for index, entry in enumerate(unique.values()):
            detail = self._fetch_detail(entry.get("id"))
            if detail:
                merged = dict(entry)
                merged.update({k: v for k, v in detail.items() if v is not None})
                enriched.append(merged)
            else:
                enriched.append(entry)
            if self._settings.detail_fetch_delay_seconds and index + 1 < len(unique):
                time.sleep(self._settings.detail_fetch_delay_seconds)

        logger.info(
            "Fetched {} MyJob.mu job records ({} unique, details merged).",
            len(enriched),
            len(unique),
        )
        return enriched

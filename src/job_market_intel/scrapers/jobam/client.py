"""Fetches raw job data from Job.am.

This module's only responsibility: make the HTTP requests (with retries
for transient failures), read the whole-board job list, enrich each
listed job with its detail page's ``JobPosting`` JSON-LD, and hand back
raw dictionaries. It does not validate individual job fields — that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-10-05)
-------------------------------------------------
Job.am (Armenia) is a server-rendered board (ASP.NET MVC, Cloudflare
front) that publishes a plain JSON endpoint:

* **List** — ``GET https://job.am/api/jobs`` returns the *entire* board
  as a bare JSON array in one response (~1,136 items, ~350 KB): exactly
  nine keys per item (``Id``, ``Title``, ``Company``, ``Url``, ``Logo``,
  ``DeadLine``, ``Location``, ``IndustryId``, ``IndustryIds``).
  Pagination query parameters (``?page=2``, ``?offset=…``) are silently
  ignored — every combination returns the same whole-board array (two
  differently-parameterized fetches differed only by a job posted in
  between). No auth, no cookies, no signing; the research User-Agent is
  accepted as-is.
* **Detail** — each item's ``Url`` (a public ``/job/{slug}-{id}`` page)
  carries a schema.org ``JobPosting`` JSON-LD ``<script>`` block — the
  only place posting date, description, and employment type exist. The
  list payload has none of the three, so this second fetch is required
  (gated behind ``fetch_details``).

Dead listings: the list API keeps serving entries whose page already
404s (6 of the first 100 on 2026-10-05). A 404 is a *permanent* HTTP
error, so it is not retried — the entry is returned without ``_detail``
and the parser skips it for lack of a posting date. Transient detail
failures are logged and skipped the same way: one job's fields are
never worth failing the run over.

``robots.txt`` disallows ``/api/*`` to crawlers; the endpoint is nonetheless
the board's own public data feed and answers plain GETs (it is listed in
the project's scrapeability audit as a FREE-API source). One list request
plus at most ``max_jobs_per_run`` detail requests per run keeps the load
trivially polite.
"""

from __future__ import annotations

import json
import re
import time

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_html, fetch_json
from job_market_intel.common.retry import call_with_retry

from .config import JobAmSettings
from .exceptions import JobAmFetchError, JobAmResponseError

# The detail page may carry several JSON-LD blocks (Organization,
# BreadcrumbList, …); the JobPosting one is the target, so extraction
# scans every block instead of taking the first.
_JSONLD_PATTERN = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)


class JobAmClient:
    """Fetches the current Job.am job records."""

    def __init__(self, settings: JobAmSettings | None = None) -> None:
        self._settings = settings or JobAmSettings()

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
            raise JobAmFetchError(
                f"Could not reach Job.am ({what}) after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobAmFetchError(f"Job.am request failed permanently ({what}): {exc}") from exc

    def _get_detail_page(self, url: str, job_id: object) -> str | None:
        """Fetch one job's public page; None if it can't be fetched.

        None only costs that job's parseable detail fields (posting
        date, description, employment type) — the list entry still
        carries title/company/location/… — so detail failures are
        logged and skipped rather than failing the run. A 404 (dead
        listing still served by the list API) is expected at a low
        rate and logged at debug level; the parser's posting-date
        requirement does the final skipping.
        """
        try:
            return call_with_retry(
                fetch_html,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
            )
        except PermanentHTTPError as exc:
            logger.debug(
                "Job.am job {} detail page permanently unavailable ({}); "
                "treating as a dead listing.",
                job_id,
                exc,
            )
            return None
        except TransientHTTPError as exc:
            logger.warning(
                "Could not reach Job.am detail for job {} after {} attempts: {}",
                job_id,
                self._settings.max_retry_attempts,
                exc,
            )
            return None

    @staticmethod
    def _extract_job_posting(page_html: str, job_id: object) -> dict | None:
        """Pull the ``JobPosting`` JSON-LD block out of a detail page."""
        for match in _JSONLD_PATTERN.finditer(page_html):
            candidate = match.group(1).strip()
            try:
                payload = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
                return payload
        logger.warning(
            "Job.am job {} page carried no JobPosting JSON-LD; the job will "
            "be skipped at parse time.",
            job_id,
        )
        return None

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch the whole-board list, then enrich the capped prefix.

        Returns:
            A list of raw job dictionaries in Job.am's own field naming:
            the list payload with the detail page's JSON-LD nested under
            ``_detail`` (when it could be fetched), capped at
            ``max_jobs_per_run`` items in the board's own display order.

        Raises:
            JobAmFetchError: If the list request failed after exhausting
                retries.
            JobAmResponseError: If the payload wasn't a usable job list.
        """
        payload = self._get_json(self._settings.list_url, what="job list")
        if not isinstance(payload, list):
            raise JobAmResponseError(
                f"Job.am job list returned {type(payload).__name__}, expected a "
                "JSON array. The API's response shape may have changed."
            )

        # One GET returns the whole board; de-duplicate by Id (defensive —
        # no duplicates observed), then take the cap in the board's own
        # default display order.
        unique: dict[object, dict] = {}
        for entry in payload:
            if not isinstance(entry, dict) or entry.get("Id") is None:
                continue
            unique.setdefault(entry["Id"], entry)
        listed = list(unique.values())

        if not listed:
            raise JobAmResponseError(
                "Job.am returned zero recognizable job records. The payload "
                "shape may have changed, or this may be an empty/blocked "
                "response."
            )

        capped = listed[: self._settings.max_jobs_per_run]
        logger.info(
            "Job.am list: {} jobs on the board, processing {} this run.",
            len(listed),
            len(capped),
        )

        if not self._settings.fetch_details:
            logger.info("Fetched {} Job.am jobs (details disabled).", len(capped))
            return capped

        enriched: list[dict] = []
        detail_failures = 0
        for index, entry in enumerate(capped):
            merged = dict(entry)
            detail_url = entry.get("Url")
            if isinstance(detail_url, str) and detail_url:
                page_html = self._get_detail_page(detail_url, entry.get("Id"))
                if page_html:
                    posting = self._extract_job_posting(page_html, entry.get("Id"))
                    if posting:
                        merged["_detail"] = posting
                    else:
                        detail_failures += 1
                else:
                    detail_failures += 1
            enriched.append(merged)
            if self._settings.detail_fetch_delay_seconds and index + 1 < len(capped):
                time.sleep(self._settings.detail_fetch_delay_seconds)

        logger.info(
            "Fetched {} Job.am job records ({} detailed, {} without usable "
            "detail — expected dead listings or transient misses).",
            len(enriched),
            len(capped) - detail_failures,
            detail_failures,
        )
        return enriched

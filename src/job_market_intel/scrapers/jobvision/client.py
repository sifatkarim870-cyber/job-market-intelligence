"""Fetches raw job data from Jobvision.

This module's only responsibility: discover job ids from the public
sitemap, fetch each job's record from the public detail API, and hand
back raw dictionaries. It does not validate individual job fields —
that is ``parser.py``'s job. Same fetch/validate/decide separation the
other scrapers establish.

Where the data lives (confirmed live, 2026-10-07)
---------------------------------------------------
Jobvision serves both halves of the scraper in the open:

* **Discovery — ``/sitemap/jobposts.xml``** (robots.txt is permissive
  and lists it via ``sitemap.xml``): a 27 MB document holding
  **60,191 unique job URLs** ``/jobs/{id}/{persian-slug}`` with
  ``lastmod`` values, interleaved with company-logo and job-image URLs
  (``/company/logo/*``, ``/jobpost/image/*`` — deliberately ignored:
  the id-anchored job regex cannot match them). Entries are **not**
  ordered newest-first, so the walk relies on skip-known exclusion
  (``exclude_ids`` from the pipeline) to progress deeper into the
  corpus across capped runs; ``max_jobs_per_run`` bounds how many
  *unseen* ids a run selects.
* **Detail — ``candidateapi.jobvision.ir/api/v1/JobPost/Detail?jobPostId=…``**
  returns ``{isSuccess, statusCode, message, data}`` with no auth, no
  cookies, no referrer (verified: UA-only GETs answer 200; a 10-call
  burst showed no rate-limiting). ``data`` is the same ~40-key record
  the site's own SSR page embeds. An ``isSuccess: false`` answer or an
  empty/``data``-less body means the job is gone — a stale sitemap
  entry costs one page, not the run (the exact failure mode that
  stalled the Glints backfill on HTTP 410 the same day).

Failure taxonomy, mirroring the fixed Glints client:

* A **permanent** HTTP error on one detail fetch (404/410 — job
  removed since the sitemap was written) is logged and skipped.
* **Transient** exhaustion (timeouts, 5xx after retries) propagates:
  that is the API being down, not a dead link.
* A non-JSON answer or a successful-but-empty envelope propagates from
  ``_fetch_job`` only when it is a *shape change* affecting every job
  (non-JSON); per-job soft failures (``isSuccess: false``, missing
  ``data.id``) skip. If every selected job ends up skipped,
  ``fetch_raw_jobs`` raises ``JobvisionResponseError`` — a fully broken
  site fails loudly, never as a silent zero-jobs no-op.
"""

from __future__ import annotations

import re
import time

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import JobvisionSettings
from .exceptions import JobvisionFetchError, JobvisionResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: A job URL inside the sitemap: ``https://jobvision.ir/jobs/{id}/{slug}``
#: terminated by ``</loc>`` / whitespace / quote. Image URLs
#: (``/company/logo/…``, ``/jobpost/image/…``) carry no ``/jobs/{digits}/``
#: segment and can never match.
_JOB_URL_RE = re.compile(r"https://jobvision\.ir/jobs/(\d+)/[^<\s\"']+")


class JobvisionClient:
    """Discovers ids via the sitemap and fetches records via the detail API."""

    def __init__(self, settings: JobvisionSettings | None = None) -> None:
        self._settings = settings or JobvisionSettings()
        # One keep-alive session: a full-corpus crawl makes ~60k API
        # calls that would pay a fresh TCP+TLS handshake each without it.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json,text/html,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _get(self, url: str, *, what: str) -> requests.Response:
        """GET one URL with retries; classify failures into the shared taxonomy."""
        settings = self._settings

        def _do() -> requests.Response:
            try:
                response = self._session.get(url, timeout=settings.request_timeout_seconds)
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientHTTPError(str(exc)) from exc
            except requests.RequestException as exc:
                raise PermanentHTTPError(str(exc)) from exc

            if response.status_code in _RETRYABLE_STATUS:
                raise TransientHTTPError(f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise PermanentHTTPError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
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
            raise JobvisionFetchError(
                f"Could not reach Jobvision ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobvisionFetchError(
                f"Jobvision request failed permanently ({what}): {exc}"
            ) from exc

    def _request_text(self, url: str, *, what: str) -> str:
        """GET one URL as text (used for the XML sitemap)."""
        return self._get(url, what=what).text

    def _request_json(self, url: str, *, what: str) -> dict:
        """GET one URL as a JSON object.

        A non-JSON answer is a shape change (or a bot wall) affecting
        every request to the endpoint — it raises instead of being
        skippable, so a broken site fails loudly.
        """
        response = self._get(url, what=what)
        try:
            body = response.json()
        except ValueError as exc:
            raise JobvisionFetchError(
                f"Jobvision {what} returned non-JSON (payload shape "
                f"change or block?): {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise JobvisionFetchError(
                f"Jobvision {what} returned a non-object JSON payload."
            )
        return body

    # -- discovery -------------------------------------------------------
    def _select_jobs(self, exclude_ids: set[str] | None = None) -> list[tuple[str, str]]:
        """First ``max_jobs_per_run`` *unseen* job ids in sitemap order.

        Args:
            exclude_ids: Stringified job ids the database already has
                (the pipeline passes
                ``repository.get_all_source_job_ids`` here). Excluded
                ids cost nothing — dropped during the scan — so a capped
                run fetches only *unseen* jobs. ``None``/empty means
                "select the head of the sitemap" (fresh scrape,
                ``--no-db`` runs).

        Returns:
            Pairs of (job id, canonical sitemap URL). The URL is what
            ``original_url`` stores (Persian slug included, verbatim).
            First occurrence wins (duplicate ids are not expected, but
            deduping keeps the window honest either way).
        """
        text = self._request_text(self._settings.sitemap_url, what="job sitemap")
        excluded = exclude_ids or set()
        limit = self._settings.max_jobs_per_run
        selected: dict[str, str] = {}
        for match in _JOB_URL_RE.finditer(text):
            job_id = match.group(1)
            if job_id in selected or job_id in excluded:
                continue
            selected[job_id] = match.group(0)
            if len(selected) >= limit:
                break

        logger.info(
            "Jobvision discovery selected {} unique jobs (window {} from "
            "jobposts sitemap, {} known excluded).",
            len(selected),
            limit,
            len(excluded),
        )
        return list(selected.items())

    # -- detail ----------------------------------------------------------
    def _detail_url(self, job_id: str) -> str:
        return f"{self._settings.detail_api_url}?jobPostId={job_id}"

    def _fetch_job(self, job_id: str) -> dict | None:
        """Fetch one job's ``data`` payload; None if it cannot be used.

        Permanent HTTP errors (the sitemap outliving its job —
        404/410 observed as the Glints failure mode) and soft API
        failures (``isSuccess: false``, empty ``data``) skip the job
        with a warning; transient exhaustion and non-JSON shape changes
        propagate (site-wide problems, not dead links).
        """
        try:
            body = self._request_json(self._detail_url(job_id), what=f"job {job_id}")
        except JobvisionFetchError as exc:
            if isinstance(exc.__cause__, PermanentHTTPError):
                logger.warning(
                    "Skipping Jobvision job {}: {} (stale sitemap entry "
                    "costs one page, not the run).",
                    job_id,
                    exc,
                )
                return None
            raise

        if not body.get("isSuccess"):
            logger.warning(
                "Skipping Jobvision job {}: API reported failure ({!r}).",
                job_id,
                str(body.get("message"))[:120],
            )
            return None
        data = body.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            logger.warning(
                "Skipping Jobvision job {}: no usable detail payload "
                "(removed job, or API shape change).",
                job_id,
            )
            return None
        return data

    def fetch_raw_jobs(self, exclude_ids: set[str] | None = None) -> list[dict]:
        """Discover unseen jobs and fetch their detail records.

        Args:
            exclude_ids: Already-stored job ids to skip at discovery
                (pipeline passes the repository's set; ``None`` for a
                plain head-of-sitemap window).

        Returns:
            Raw records ``{"url": canonical sitemap URL, "payload": API
            data dict}``.

        Raises:
            JobvisionFetchError: If a request failed after exhausting
                retries, or the sitemap/API stopped serving JSON.
            JobvisionResponseError: If discovery returned zero job
                URLs without an exclusion (format change / unreachable
                site) or every selected job yielded no usable record.
        """
        selected = self._select_jobs(exclude_ids=exclude_ids)
        if not selected:
            if exclude_ids:
                # Skip-known drained the whole sitemap without finding
                # an unseen id: the corpus is fully covered. That is a
                # successful no-op, not a discovery failure.
                logger.info(
                    "Jobvision discovery found no unseen jobs ({} known "
                    "excluded); corpus fully covered this run.",
                    len(exclude_ids),
                )
                return []
            raise JobvisionResponseError(
                "Jobvision sitemap discovery returned zero job URLs. The "
                "format may have changed, or the site may be unreachable."
            )

        settings = self._settings
        jobs: list[dict] = []
        for index, (job_id, canonical_url) in enumerate(selected):
            data = self._fetch_job(job_id)
            if data is not None:
                jobs.append({"url": canonical_url, "payload": data})
            if settings.fetch_delay_seconds and index + 1 < len(selected):
                time.sleep(settings.fetch_delay_seconds)
            if (index + 1) % 50 == 0:
                logger.info(
                    "Jobvision detail fetches: {}/{} (records: {}).",
                    index + 1,
                    len(selected),
                    len(jobs),
                )

        if not jobs:
            raise JobvisionResponseError(
                "Jobvision returned zero job records across all fetched ids. "
                "The API payload shape may have changed, or the responses "
                "were blocked/empty."
            )

        logger.info(
            "Fetched {} Jobvision job records ({} ids selected).",
            len(jobs),
            len(selected),
        )
        return jobs

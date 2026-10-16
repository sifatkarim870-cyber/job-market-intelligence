"""Fetches raw postings from CareerJunction, a South African job board.

Two steps:

  1. **Discovery.** Walk ``/jobs``, collecting ``/<slug>-job-<id>.aspx`` links.
     Measured 2026-10-17: exactly **25** per page. The pager is **ignored**:
     ``?page=2`` returns the same 25 links as page 1, so only one page is
     walked.

  2. **Detail.** Fetch each link and read the schema.org ``JobPosting`` in its
     JSON-LD block. The JSON is malformed (raw newlines in the description), so
     the parser uses ``json.loads(block, strict=False)``.

robots.txt is real ``text/plain`` (128 bytes). The governing ``*`` group is
``Allow: /``, disallowing only ``/myprofile/applied-jobs`` and
``/myprofile/EditProfile``. ``/jobs`` and ``/<slug>-job-<id>.aspx`` are
permitted.
"""

from __future__ import annotations

import re
import time

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import CareerJunctionSettings
from .exceptions import CareerJunctionFetchError, CareerJunctionResponseError

#: ``/<slug>-job-<numeric id>.aspx``. The id is 5-12 digits.
_JOB_LINK = re.compile(r'href="(/[^"?#]{6,140}-job-(\d{5,12})\.aspx)"')


class CareerJunctionClient:
    """Fetches postings from CareerJunction's server-rendered listing and detail pages."""

    def __init__(self, settings: CareerJunctionSettings | None = None) -> None:
        self._settings = settings or CareerJunctionSettings()

    # ------------------------------------------------------------------ fetch

    def _fetch(self, url: str) -> str:
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
            raise CareerJunctionFetchError(
                f"CareerJunction unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise CareerJunctionFetchError(f"CareerJunction refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page. Page 1 omits the query entirely."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one page of the listing."""
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            found.setdefault(m.group(2), m.group(1))
        logger.info("careerjunction listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    # ------------------------------------------------------------- discovery

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk the listing, collecting detail paths.

        Returns ``({job_id: {"path": ..., "page": ...}}, failures)``.
        """
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except CareerJunctionFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("careerjunction listing page {} failed: {}", page, exc)
                break

            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue

            new = 0
            for job_id, path in links.items():
                if job_id not in found:
                    found[job_id] = {"path": path, "page": page}
                    new += 1

            # Collect first, stop second: a short final page still holds real
            # postings, and discarding it loses the tail of every run.
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "careerjunction page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise CareerJunctionResponseError(
                f"no postings found in {self._settings.max_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result here means the "
                "listing markup changed -- not that the board is empty -- so it "
                "is raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures.

        Failures are collected rather than raised: one posting or one listing
        page failing must not cost a run.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for job_id, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except CareerJunctionFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("careerjunction job page {} failed: {}", job_id, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": job_id,
                    "html": html,
                    "url": url,
                    "listing_page": meta["page"],
                }
            )

        if not records and not failures:
            raise CareerJunctionResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("careerjunction: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

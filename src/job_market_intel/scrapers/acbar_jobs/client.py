"""Fetches raw postings from the ACBAR jobs board (Afghanistan).

Discovery walks ``/en/jobs?page=N``: **20** posting links per page, and
``?page=2`` returns **20 new** paths. ``/en/site-page/2`` is HTTP 404 -- that is
the pagination *chrome*, not the pager, and confusing the two is the obvious way
to conclude the board does not paginate.

Hrefs are **absolute** (measured 20 absolute, 0 relative); the host prefix in
:data:`_JOB_LINK` is optional so both spellings match. Angola Emprego was the same
way and a relative-only pattern there matched nothing at all.

robots.txt is 24 bytes -- ``User-agent: *`` with an empty ``Disallow:`` -- so the
whole site is permitted.
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

from .config import AcbarJobsSettings
from .exceptions import AcbarJobsFetchError, AcbarJobsResponseError

#: ``/en/jobs/details/<id>/<slug>``. The id is the stable key.
_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/en/jobs/details/(\d+)/[^"?#]{2,160}/?)"')


class AcbarJobsClient:
    """Fetches postings from ACBAR's server-rendered pages."""

    def __init__(self, settings: AcbarJobsSettings | None = None) -> None:
        self._settings = settings or AcbarJobsSettings()

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
            raise AcbarJobsFetchError(
                f"ACBAR unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise AcbarJobsFetchError(f"ACBAR refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page. ``?page=`` -- the pager, not the chrome."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one page of the listing."""
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            found.setdefault(m.group(2), m.group(1))
        logger.info("acbar listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    # ------------------------------------------------------------- discovery

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk the listing, collecting detail paths."""
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except AcbarJobsFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("acbar listing page {} failed: {}", page, exc)
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

            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "acbar page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise AcbarJobsResponseError(
                f"no postings found in {self._settings.max_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result here means the "
                "listing markup changed -- not that the board is empty -- so it "
                "is raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures."""
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
                except AcbarJobsFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("acbar job page {} failed: {}", job_id, exc)
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
            raise AcbarJobsResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("acbar: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

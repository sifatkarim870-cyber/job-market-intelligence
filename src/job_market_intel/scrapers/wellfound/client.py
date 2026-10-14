"""Fetches raw postings from Wellfound, the startup job board.

Two steps, as for every HTML source:

  1. **Discovery.** Walk ``/location/<country>`` and ``/role/l/<role>/<country>``
     with ``?page=N`` and collect ``/jobs/<id>-<slug>`` links. Each listing page
     is 600-860 KB and yields 45-58 *distinct* jobs.

     ``/jobs`` is deliberately not walked. It returns HTTP 200, renders a
     ``page=N`` pager, and then ignores the parameter: pages 1 through 11 each
     returned the identical 43 job ids and zero new ones (measured 2026-10-14).
     Walking it would spend the entire request budget re-reading page 1.

  2. **Detail.** Fetch each link and read the schema.org ``JobPosting`` JSON-LD
     block. Listing pages carry only a slug, so this step is where all the data
     is.
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

from .config import WellfoundSettings
from .exceptions import WellfoundFetchError, WellfoundResponseError

#: ``/jobs/<numeric id>-<slug>``. The id is the natural key and the slug is
#: decoration, so the id is captured separately and the slug is never used for
#: identity -- slugs change when a title is edited.
_JOB_LINK = re.compile(r'href="(/jobs/(\d{3,12})-[^"#?]{2,90})"')

#: A page is only considered a real listing page if it renders job links. Used
#: to tell "past the end" from "still going" rather than guessing from status.
_MIN_LINKS_PER_PAGE = 5


class WellfoundClient:
    """Fetches postings from Wellfound's server-rendered listing and detail pages."""

    def __init__(self, settings: WellfoundSettings | None = None) -> None:
        self._settings = settings or WellfoundSettings()

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
            raise WellfoundFetchError(
                f"Wellfound unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise WellfoundFetchError(f"Wellfound refused {url}: {exc}") from exc

    def listing_url(self, path: str, page: int = 1) -> str:
        """URL for one page of a listing. Page 1 omits the query entirely."""
        base = f"{self._settings.base_url}{path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, path: str, page: int = 1) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one page of a listing.

        An empty dict means the listing is exhausted or the page stopped
        rendering links; the caller decides whether that is expected.
        """
        html = self._fetch(self.listing_url(path, page))
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        logger.info("wellfound listing {!r} page {}: {} link(s)", path, page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def _walk_listing(
        self,
        path: str,
        found: dict[str, dict[str, str]],
        failures: dict[str, str],
    ) -> bool:
        """Walk one listing path, adding to ``found``. False means budget exhausted.

        Stopping rules, in order:
          * repeated empty pages -- the listing is exhausted;
          * a page with fewer than ``_MIN_LINKS_PER_PAGE`` links -- the tail,
            where a short page is normal rather than an error;
          * ``max_pages_per_listing`` -- the configured budget.
        """
        empty_streak = 0
        for page in range(1, self._settings.max_pages_per_listing + 1):
            try:
                links = self.fetch_listing_page(path, page)
            except WellfoundFetchError as exc:
                failures[f"{path}?page={page}"] = str(exc)
                logger.warning("wellfound listing {} page {} failed: {}", path, page, exc)
                break
            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue
            empty_streak = 0
            new = 0
            for job_id, detail in links.items():
                # First listing wins, so a posting reachable from two listings
                # is fetched -- and recorded -- exactly once.
                if job_id not in found:
                    found[job_id] = {"path": detail, "listing": path}
                    new += 1
            # Collect first, stop second. A listing's final page is short
            # because it is the tail, not because it is empty, and those
            # postings are real; discarding them loses the last page of every
            # listing walked.
            short_page = len(links) < _MIN_LINKS_PER_PAGE
            logger.info(
                "wellfound listing {!r} page {}: {} new ({} total){}",
                path,
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                return len(found) < self._settings.max_jobs_per_run
        return True

    def discover_detail_paths(self) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
        """Walk every listing page, collecting detail paths.

        Returns ``({job_id: {"path": ..., "listing": ...}}, failures)``.
        """
        found: dict[str, dict[str, str]] = {}
        failures: dict[str, str] = {}

        for path in self._settings.listing_paths:
            if not self._walk_listing(path, found, failures):
                logger.info("wellfound: job budget reached during discovery")
                return found, failures

        if not found and not failures:
            raise WellfoundResponseError(
                "no job links found across "
                f"{len(self._settings.listing_paths)} listing(s). Wellfound's "
                "listing pages are the only discovery route -- /jobs ignores "
                "its page parameter -- so an empty result means the markup "
                "changed, not that the board is empty. Raised rather than "
                "returned empty so the two cannot be confused."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures.

        Failures are collected rather than raised: one posting or one listing
        failing must not cost a run.
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
                except WellfoundFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("wellfound job page {} failed: {}", job_id, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": job_id,
                    "html": html,
                    "url": url,
                    "listing_path": meta["listing"],
                }
            )

        if not records and not failures:
            raise WellfoundResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("wellfound: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

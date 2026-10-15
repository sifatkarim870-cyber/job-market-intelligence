"""Fetches raw postings from Built In, the US tech job board.

Two steps:

  1. **Discovery.** Walk ``/jobs`` and ``/jobs/<facet>`` with ``?page=N``,
     collecting ``/job/<slug>/<id>`` links. Measured 2026-10-15: 182 distinct
     links over 8 pages, 20-27 per page, pager offering up to 1000.

     robots.txt disallows ``/search/`` and ``/jobs*?search=``, so discovery
     cannot be keyword-driven and no such path appears in the settings. It
     allows ``?page=`` on a ``/jobs`` path via ``Allow: /jobs*?page=``, which is
     the longer and therefore governing match.

  2. **Detail.** Fetch each link and read the schema.org ``JobPosting`` that
     sits inside the page's ``@graph`` JSON-LD document. Listing pages carry
     only a slug and an id.
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

from .config import BuiltInSettings
from .exceptions import BuiltInFetchError, BuiltInResponseError

#: ``/job/<slug>/<numeric id>``. The id trails the slug, unlike Wellfound's
#: leading-id URLs. The slug is decoration -- it changes when a title is
# edited -- so only the id is kept.
_JOB_LINK = re.compile(r'href="(/job/[^"#?]{2,110}/(\d{4,12}))"')


class BuiltInClient:
    """Fetches postings from Built In's server-rendered listing and detail pages."""

    def __init__(self, settings: BuiltInSettings | None = None) -> None:
        self._settings = settings or BuiltInSettings()

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
            raise BuiltInFetchError(
                f"Built In unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise BuiltInFetchError(f"Built In refused {url}: {exc}") from exc

    def listing_url(self, path: str, page: int = 1) -> str:
        """URL for one page of a listing. Page 1 omits the query entirely."""
        base = f"{self._settings.base_url}{path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, path: str, page: int = 1) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one page of a listing."""
        html = self._fetch(self.listing_url(path, page))
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        logger.info("builtin listing {!r} page {}: {} link(s)", path, page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def _walk_listing(
        self,
        path: str,
        found: dict[str, dict[str, str]],
        failures: dict[str, str],
    ) -> bool:
        """Walk one listing path, adding to ``found``. False means budget exhausted."""
        empty_streak = 0
        for page in range(1, self._settings.max_pages_per_listing + 1):
            try:
                links = self.fetch_listing_page(path, page)
            except BuiltInFetchError as exc:
                failures[f"{path}?page={page}"] = str(exc)
                logger.warning("builtin listing {} page {} failed: {}", path, page, exc)
                break
            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue

            new = 0
            for job_id, detail in links.items():
                # First listing wins, so a posting reachable from two facets is
                # fetched -- and recorded -- exactly once.
                if job_id not in found:
                    found[job_id] = {"path": detail, "listing": path}
                    new += 1
            # Collect first, stop second: a short final page still holds real
            # postings, and discarding it loses the tail of every listing.
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "builtin listing {!r} page {}: {} new ({} total){}",
                path,
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                return len(found) < self._settings.max_jobs_per_run
            empty_streak = 0
        return True

    def discover_detail_paths(self) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
        """Walk every listing page, collecting detail paths.

        Returns ``({job_id: {"path": ..., "listing": ...}}, failures)``.
        """
        found: dict[str, dict[str, str]] = {}
        failures: dict[str, str] = {}

        for path in self._settings.listing_paths:
            if not self._walk_listing(path, found, failures):
                logger.info("builtin: job budget reached during discovery")
                return found, failures

        if not found and not failures:
            raise BuiltInResponseError(
                "no job links found across "
                f"{len(self._settings.listing_paths)} listing(s). An empty result "
                "here means the listing markup changed -- not that the board is "
                "empty -- so it is raised rather than returned empty."
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
                except BuiltInFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("builtin job page {} failed: {}", job_id, exc)
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
            raise BuiltInResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("builtin: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

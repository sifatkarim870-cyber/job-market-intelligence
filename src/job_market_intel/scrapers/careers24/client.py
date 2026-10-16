"""Fetches raw postings from Careers24, the South African job board.

Two steps:

  1. **Discovery.** Walk ``/jobs?page=N``, collecting
     ``/jobs/adverts/<id>-<slug>`` links. Measured 2026-10-15: **10** adverts
     per page, 54 distinct ids over 6 pages, with the id set changing on every
     page -- so the pager is real. (That is a third page size in this project:
     Wellfound ignores ``page`` entirely and Built In serves 20-27.)

     The regex below deliberately does **not** require the href to end at the
     slug. Careers24 appends a rank query string -- ``?jobindex=2``,
     ``?jobindex=3`` -- so the first two probe passes, which anchored the
     pattern on the closing quote, matched zero adverts on a board that was
     plainly serving them, and briefly looked like an empty board.

  2. **Detail.** Fetch each link and read the schema.org ``JobPosting`` at the
     top level of its JSON-LD (12 of 12 fields present on all 8 postings
     measured). Listing pages carry only an id, a slug and a rank.

robots.txt lists ~16 named user-agent groups, several with ``Disallow: /``, but
there is **no** ``User-agent: *`` group. Under RFC 9309 that leaves the crawler
unrestricted by this file, which ``urllib.robotparser`` agrees with. See
:mod:`.config` for why that is worth stating rather than inferring.
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

from .config import Careers24Settings
from .exceptions import Careers24FetchError, Careers24ResponseError

#: ``/jobs/adverts/<numeric id>-<slug>``. The slug is decoration -- it changes
#: when a title is edited -- so only the id is kept, and the path is truncated
#: before any ``?jobindex=`` rank so the detail URL stays canonical.
_JOB_LINK = re.compile(r'href="([^"]*?/jobs/adverts/(\d+)-[^"?#]+)')


class Careers24Client:
    """Fetches postings from Careers24's server-rendered listing and detail pages."""

    def __init__(self, settings: Careers24Settings | None = None) -> None:
        self._settings = settings or Careers24Settings()

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
            raise Careers24FetchError(
                f"Careers24 unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise Careers24FetchError(f"Careers24 refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page. Page 1 omits the query entirely."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one page of the listing."""
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            # Anchor the path at /jobs/adverts/ so a link that happened to carry
            # an absolute or protocol-relative prefix still normalises.
            path = m.group(1)
            idx = path.index("/jobs/adverts/")
            found[m.group(2)] = path[idx:]
        logger.info("careers24 listing page {}: {} link(s)", page, len(found))
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
            except Careers24FetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("careers24 listing page {} failed: {}", page, exc)
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
                "careers24 page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise Careers24ResponseError(
                f"no adverts found in {self._settings.max_pages} page(s) of "
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
                except Careers24FetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("careers24 job page {} failed: {}", job_id, exc)
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
            raise Careers24ResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("careers24: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

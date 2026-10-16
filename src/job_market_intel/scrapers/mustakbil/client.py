"""Fetches raw postings from Mustakbil, a large Pakistani job board.

Discovery is **breadth by category, not pagination**:

  1. **Listing.** Walk each configured path once. ``/jobs`` yields 43 posting
     ids; ``/jobs?page=2`` is byte-identical (398,957 bytes, same 43 ids), so
     the ``page`` parameter is ignored -- the same trap as Wellfound, and the
     reason no page parameter appears in the settings. Breadth comes from
     ``/jobs/pakistan/<slug>``: of 25 plausible slugs measured, 8 return HTTP
     200 with job links and 17 return 404. Those 8 add 80 ids beyond the
     baseline, for 123 distinct postings across nine paths.

  2. **Detail.** Fetch each ``/jobs/job/<id>`` and read the schema.org
     ``JobPosting`` at the top level of its JSON-LD.

robots.txt (1,882 bytes, real ``text/plain``) has a ``User-agent: *`` group with
``Allow: /``, disallowing only ``/clearCache``, ``/clearcache`` and
``/content/images/ads/`` -- none of which is a job path. The named groups
(SemrushBot, AhrefsBot, PetalBot, DotBot, ...) mostly carry ``Disallow: /``,
which does not apply to this crawler.

**The site rate-limits hard and does it at the connection level.** A burst of
listing fetches succeeds, then every detail fetch fails with
``ConnectionError`` until a multi-minute cool-off; measured 3.5s between
requests was not enough where 75s of total quiet was. The default delay is
therefore 4.0s, an order of magnitude above the politest setting in this
project, and it is not negotiable downwards without re-measuring.
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

from .config import MustakbilSettings
from .exceptions import MustakbilFetchError, MustakbilResponseError

#: ``/jobs/job/<numeric id>``. The id is the whole path.
_JOB_LINK = re.compile(r'href="(/jobs/job/(\d{5,12})[^"?#]*)"')


class MustakbilClient:
    """Fetches postings from Mustakbil's server-rendered listing and detail pages."""

    def __init__(self, settings: MustakbilSettings | None = None) -> None:
        self._settings = settings or MustakbilSettings()

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
            raise MustakbilFetchError(
                f"Mustakbil unreachable after {self._settings.max_retry_attempts} "
                f"attempts: {exc}. The site rate-limits at the connection level, "
                "so if this fires on a run that worked before, the fix is a "
                "longer backoff, not a faster retry."
            ) from exc
        except PermanentHTTPError as exc:
            raise MustakbilFetchError(f"Mustakbil refused {url}: {exc}") from exc

    def listing_url(self, path: str) -> str:
        """URL for a listing path. Deliberately no page parameter."""
        return f"{self._settings.base_url}{path}"

    def fetch_listing_page(self, path: str) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one listing path."""
        html = self._fetch(self.listing_url(path))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            found.setdefault(m.group(2), m.group(1))
        logger.info("mustakbil listing {!r}: {} link(s)", path, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    # ------------------------------------------------------------- discovery

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk every listing path once, collecting detail paths.

        Every configured path is walked, deliberately. An earlier version broke
        out of this loop as soon as ``max_jobs_per_run`` was reached, and since
        ``/jobs`` alone yields 43 ids, running with ``--max-jobs 40`` stopped
        discovery after the first path -- so the eight category paths, which are
        the entire reason this board is worth building because it has no
        pagination, were never requested.

        The path list is fixed and measured (9 paths, each verified HTTP 200),
        so walking all of them costs 9 requests and is bounded by construction.
        ``max_jobs_per_run`` governs detail *fetching*, not discovery.

        Returns ``({job_id: {"path": ..., "listing": ...}}, failures)``.
        """
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}

        for path in self._settings.listing_paths:
            try:
                links = self.fetch_listing_page(path)
            except MustakbilFetchError as exc:
                failures[path] = str(exc)
                logger.warning("mustakbil listing {!r} failed: {}", path, exc)
                continue

            new = 0
            for job_id, detail in links.items():
                if job_id not in found:
                    found[job_id] = {"path": detail, "listing": path}
                    new += 1

            # Collect first, stop second: a small category (security had 2 ids,
            # pharmacy 4) still holds real postings.
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "mustakbil {!r}: {} new ({} total){}",
                path,
                new,
                len(found),
                " [small page, keeping what it had]" if short_page else "",
            )

        logger.info(
            "mustakbil: discovered {} distinct posting(s) across {} path(s)",
            len(found),
            len(self._settings.listing_paths),
        )

        if not found and not failures:
            raise MustakbilResponseError(
                f"no job links found across {len(self._settings.listing_paths)} "
                "listing path(s). An empty result here means the listing markup "
                "changed -- not that the board is empty -- so it is raised "
                "rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures.

        Failures are collected rather than raised: one posting or one listing
        path failing must not cost a run.
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
                except MustakbilFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("mustakbil job page {} failed: {}", job_id, exc)
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
            raise MustakbilResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("mustakbil: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

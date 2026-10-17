"""Fetches raw postings from Jobs.af, an Afghan job board.

Discovery is the **homepage**: ``/public/job/page/2`` is HTTP 404,
``/public/job?page=2`` adds 0 new, and re-fetching ``/`` adds 0 new. All **12**
postings are on one page, so the whole board is a single request.

Hrefs are **relative** (measured 12 relative, 0 absolute); the host prefix in
:data:`_JOB_LINK` is optional so both spellings match, because Angola Emprego was
the opposite way and a relative-only pattern there matched nothing at all.

robots.txt is real ``text/plain`` (661 bytes): ``User-agent: *`` is ``Allow: /``
and disallows only ``/dashboard``, ``/discover``, ``/talents``, ``/projects`` and
``/wallet``. ``/public/job/`` is permitted.
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

from .config import JobsAfSettings
from .exceptions import JobsAfFetchError, JobsAfResponseError

#: ``/public/job/<slug>``. Slugs are hyphenated words, sometimes ending in a
#: numeric suffix ("assistant-branch-manager-31") and sometimes not.
_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/public/job/[a-z0-9][^"?#]{2,180}/?)"')
#: Paths under /public/job/ that are not postings.
_CHROME = {"page", "search", "browse", "category", "categories", "index"}


def _is_posting_slug(slug: str) -> bool:
    """Whether a ``/public/job/<slug>`` path is a posting.

    Whole-segment matching only: a substring test on a chrome word would throw
    away a real posting such as ``branch-manager-kunduz-branch-16``.
    """
    if not slug or slug.lower() in _CHROME:
        return False
    return not slug.isdigit()


class JobsAfClient:
    """Fetches postings from Jobs.af's server-rendered pages."""

    def __init__(self, settings: JobsAfSettings | None = None) -> None:
        self._settings = settings or JobsAfSettings()

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
            raise JobsAfFetchError(
                f"Jobs.af unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobsAfFetchError(f"Jobs.af refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page. The board has no pager, so this is the root."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{slug: detail_path}`` for one page of the listing."""
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            path = m.group(1)
            slug = path.strip("/").split("/")[-1]
            if not _is_posting_slug(slug):
                continue
            found.setdefault(slug, path)
        logger.info("jobs_af listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    # ------------------------------------------------------------- discovery

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Collect detail paths. Returns ``({slug: {...}}, failures)``."""
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except JobsAfFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobs_af listing page {} failed: {}", page, exc)
                break
            if not links:
                break
            new = 0
            for slug, path in links.items():
                if slug not in found:
                    found[slug] = {"path": path, "page": page}
                    new += 1
            logger.info("jobs_af page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found and not failures:
            raise JobsAfResponseError(
                f"no postings found at {self._settings.listing_path}. An empty "
                "result here means the markup changed -- not that the board is "
                "empty -- so it is raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures."""
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for slug, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except JobsAfFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("jobs_af job page {} failed: {}", slug, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": slug,
                    "html": html,
                    "url": url,
                    "listing_page": meta["page"],
                }
            )

        if not records and not failures:
            raise JobsAfResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("jobs_af: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

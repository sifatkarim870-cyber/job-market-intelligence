"""Fetches raw postings from Job in Rwanda.

Discovery is the **homepage**, not a listing path: ``/jobs`` is HTTP 404 and
``/?page=2`` returns 0 new postings, so the pager does not exist and the single
homepage carries all **199** ``/job/<slug>`` links.

The hrefs are **relative** (measured: 199 relative, 0 absolute), which is worth
stating because Angola Emprego turned out to be the opposite and cost a CI run.

robots.txt is real ``text/plain`` (1706 bytes): ``User-agent: *`` allows ``/``
and disallows only ``/core/``, ``/profiles/`` and ``/README.txt``. Job pages are
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

from .config import JobInRwandaSettings
from .exceptions import JobInRwandaFetchError, JobInRwandaResponseError

#: ``/job/<slug>``. Slugs are hyphenated words, optionally ending in a numeric
#: id (``accountant-172``).
#:
#: The host prefix is optional so both relative and absolute hrefs match.
#: Measured on this board: **199 relative, 0 absolute**. Angola Emprego was the
#: other way round and a relative-only pattern there matched nothing at all, so
#: both spellings are accepted rather than betting on one.
_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/job/[a-z0-9][^"?#]{2,180}/?)"')


class JobInRwandaClient:
    """Fetches postings from Job in Rwanda's server-rendered pages."""

    def __init__(self, settings: JobInRwandaSettings | None = None) -> None:
        self._settings = settings or JobInRwandaSettings()

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
            raise JobInRwandaFetchError(
                f"Job in Rwanda unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobInRwandaFetchError(f"Job in Rwanda refused {url}: {exc}") from exc

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
            if slug.lower() in {"page", "search", "browse"}:
                continue
            found.setdefault(slug, path)
        logger.info("jobinrwanda listing page {}: {} link(s)", page, len(found))
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
            except JobInRwandaFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobinrwanda listing page {} failed: {}", page, exc)
                break
            if not links:
                break
            new = 0
            for slug, path in links.items():
                if slug not in found:
                    found[slug] = {"path": path, "page": page}
                    new += 1
            logger.info("jobinrwanda page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found and not failures:
            raise JobInRwandaResponseError(
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
                except JobInRwandaFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("jobinrwanda job page {} failed: {}", slug, exc)
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
            raise JobInRwandaResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("jobinrwanda: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

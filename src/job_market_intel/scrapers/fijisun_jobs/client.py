"""Fetches raw postings from the Fiji Sun jobs board (Fiji).

Discovery is /jobs then /jobs/browse: the first returns 8 postings and
/jobs/browse returns 2 new. /jobs/page/2 and /jobs?page=2 both return 0 new,
so /jobs/browse is the real pager and the query form is dead.

Hrefs are relative (measured 8 relative, 0 absolute); the host prefix in
_JOB_LINK is optional so both spellings match, because Angola Emprego was the
opposite way round and a relative-only pattern there matched nothing.

robots.txt: User-agent: * allows / and disallows /api/, /admin and
/todays-paper/. Job pages are permitted.
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

from .config import FijiSunJobsSettings
from .exceptions import FijiSunJobsFetchError, FijiSunJobsResponseError

_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/jobs/[a-z0-9][^"?#]{2,180}/?)"')
_CHROME = {"browse", "page", "search", "category", "categories"}


def _is_posting_slug(slug: str) -> bool:
    """Whether a /jobs/<slug> path is a posting."""
    if not slug or slug.lower() in _CHROME:
        return False
    return not slug.isdigit()


class FijiSunJobsClient:
    """Fetches postings from the Fiji Sun jobs board."""

    def __init__(self, settings: FijiSunJobsSettings | None = None) -> None:
        self._settings = settings or FijiSunJobsSettings()

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
            raise FijiSunJobsFetchError(
                f"Fiji Sun unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise FijiSunJobsFetchError(f"Fiji Sun refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        if page <= 1:
            return base
        return f"{self._settings.base_url}{self._settings.page_path_template}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            path = m.group(1)
            slug = path.strip("/").split("/")[-1]
            if not _is_posting_slug(slug):
                continue
            found.setdefault(slug, path)
        logger.info("fijisun listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except FijiSunJobsFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("fijisun listing page {} failed: {}", page, exc)
                break

            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue

            new = 0
            for slug, path in links.items():
                if slug not in found:
                    found[slug] = {"path": path, "page": page}
                    new += 1

            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "fijisun page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise FijiSunJobsResponseError(  # noqa: UP032
                f"no postings found in {self._settings.max_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result here means the "
                "markup changed -- not that the board is empty -- so it is "
                "raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for slug, meta in discovered.items():
            if len(records) >= budget:
                break
            url = "{}{}".format(self._settings.base_url, meta["path"])
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except FijiSunJobsFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("fijisun job page {} failed: {}", slug, exc)
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
            raise FijiSunJobsResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("fijisun: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

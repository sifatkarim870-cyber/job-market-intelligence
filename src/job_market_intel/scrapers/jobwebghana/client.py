"""Fetches raw postings from Jobweb Ghana.

Discovery walks ``/jobs/`` then ``/jobs/page/N/``. Measured 2026-10-18: page 1
carries **22** posting links and ``/jobs/page/2/`` adds **13** new ones.

Two measured details that shape this:

* Hrefs are **absolute** (20 absolute, 0 relative), so the host prefix in
  :data:`_JOB_LINK` is optional rather than required. Angola Emprego was the same
  way and a relative-only pattern there matched nothing at all.
* robots.txt contains ``disallow: /*?*`` -- every query string. Pagination
  therefore uses the **path** form ``/jobs/page/2/`` and never ``?page=2``.

Detail pages carry a schema.org ``JobPosting``. The **listing** page carries only
a ``BreadcrumbList``, which is worth remembering: an early triage scored this
board as "no structured data" on the strength of the listing alone.
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

from .config import JobwebGhanaSettings
from .exceptions import JobwebGhanaFetchError, JobwebGhanaResponseError

#: ``/jobs/<slug>/``. The host prefix is optional so both relative and absolute
#: hrefs match; measured absolute here.
_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/jobs/[a-z0-9][^"?#]{2,180}/?)"')
#: The board's own paths under /jobs/ that are not postings.
_CHROME = {"feed", "page", "category", "categories", "search", "tag", "archive", "author"}


def _is_posting_slug(slug: str) -> bool:
    """Whether a ``/jobs/<slug>`` path is a posting.

    Measured: real postings always have a hyphenated word slug
    ("accounts-clerk-l-t-company"), but the listing also links bare numeric
    paths -- ``/jobs/2/``, ``/jobs/3/``, ``/jobs/1057/`` -- which are not postings
    and serve pages with no ``JobPosting``. The first live run followed those and
    spent 9 of 74 fetches on them, reporting 9 spurious "no title" issues.

    A purely numeric slug is therefore rejected here. Substring matching on
    "page" is deliberately avoided: a real slug can contain it, and requiring an
    exact match on the whole segment is the only safe reading.
    """
    if not slug or slug.lower() in _CHROME:
        return False
    return not slug.isdigit()


class JobwebGhanaClient:
    """Fetches postings from Jobweb Ghana's server-rendered pages."""

    def __init__(self, settings: JobwebGhanaSettings | None = None) -> None:
        self._settings = settings or JobwebGhanaSettings()

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
            raise JobwebGhanaFetchError(
                f"Jobweb Ghana unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobwebGhanaFetchError(f"Jobweb Ghana refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page.

        Pagination is **path-based**: robots.txt disallows ``/*?*``, so
        ``/jobs/page/2/`` is used and ``?page=2`` is not.
        """
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        if page <= 1:
            return base
        return f"{self._settings.base_url}{self._settings.page_path_template.format(page=page)}"

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
        logger.info("jobwebghana listing page {}: {} link(s)", page, len(found))
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
            except JobwebGhanaFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobwebghana listing page {} failed: {}", page, exc)
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
                "jobwebghana page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise JobwebGhanaResponseError(
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
        for slug, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except JobwebGhanaFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("jobwebghana job page {} failed: {}", slug, exc)
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
            raise JobwebGhanaResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("jobwebghana: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

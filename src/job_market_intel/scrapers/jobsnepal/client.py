"""Fetches raw postings from JobsNepal (Nepal).

Discovery is ``/top-job`` with **path-based** pagination: ``/top-job?page=2``
returned **8 new** postings. Hrefs are **relative**.

robots.txt: ``User-agent: *`` with an empty ``Disallow:`` -- the whole site is
permitted.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import JobsNepalSettings
from .exceptions import JobsNepalFetchError, JobsNepalResponseError

_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/([a-z0-9][a-z0-9-]{4,})-(\d{4,})/?)"')

#: ``/jobs-sitemap.xml`` lists every live posting, newest first, as
#: ``https://www.jobsnepal.com/<slug>-<id>`` (152 measured 2026-10-29).
#: That is 10x the 14 postings the /top-job listing shows, so it is the
#: primary discovery channel; the listing stays as the fallback.
_SITEMAP_LOC = re.compile(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", re.I)
_SITEMAP_JOB = re.compile(r"^(/[a-z0-9][a-z0-9-]*?)-(\d{4,})$", re.I)


def extract_sitemap_paths(xml: str) -> dict[str, str]:
    """Return ``{job_id: path}`` from JobsNepal's jobs sitemap."""
    found: dict[str, str] = {}
    for url in _SITEMAP_LOC.findall(xml or ""):
        path = urlparse(url).path.rstrip("/")
        match = _SITEMAP_JOB.match(path)
        if match is not None:
            found.setdefault(match.group(2), path)
    return found


class JobsNepalClient:
    """Fetches postings from JobsNepal (Nepal)."""

    def __init__(self, settings: JobsNepalSettings | None = None) -> None:
        self._settings = settings or JobsNepalSettings()

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
            raise JobsNepalFetchError(
                f"JobsNepal unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobsNepalFetchError(f"JobsNepal refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            slug = m.group(1).strip("/")
            job_id = m.group(3)
            if slug.lower() in {"category", "city", "about-us", "articles"}:
                continue
            found.setdefault(job_id, m.group(1))
        if found:
            logger.info("jobsnepal listing page {}: {} link(s)", page, len(found))
        else:
            # A 0-link page is either a bot challenge (the reason this source
            # was disabled in 2026-10-18) or a markup change; record which.
            soup = BeautifulSoup(html or "", "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            logger.warning(
                "jobsnepal listing page {}: 0 postings in a {} char page "
                "({} anchor(s), title {!r})",
                page,
                len(html or ""),
                len(soup.find_all("a", href=True)),
                title[:160],
            )
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def fetch_sitemap_paths(self) -> dict[str, str]:
        """Every live posting from ``/jobs-sitemap.xml``."""
        url = f"{self._settings.base_url}{self._settings.sitemap_path}"
        found = extract_sitemap_paths(self._fetch(url))
        logger.info("jobsnepal sitemap {}: {} posting(s)", self._settings.sitemap_path, len(found))
        return found

    def _walk_listing(self, failures: dict[str, str]) -> dict[str, dict]:
        """Fallback discovery through the server-rendered listing pages."""
        found: dict[str, dict] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except JobsNepalFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobsnepal listing page {} failed: {}", page, exc)
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
                "jobsnepal page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}

        try:
            sitemap = self.fetch_sitemap_paths()
        except JobsNepalFetchError as exc:
            failures["sitemap"] = str(exc)
            logger.warning("jobsnepal sitemap failed: {}", exc)
            sitemap = {}
        for job_id, path in sitemap.items():
            if len(found) >= self._settings.max_jobs_per_run:
                break
            found[job_id] = {"path": path, "page": 0}

        if not found:
            found = self._walk_listing(failures)

        if not found:
            raise JobsNepalResponseError(  # noqa: UP032
                f"no postings found in {self._settings.sitemap_path} or "
                f"{self._settings.max_pages} page(s) of {self._settings.listing_path}. "
                "An empty result here means a wall or a markup change -- not that "
                "the board is empty -- so it is raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for job_id, meta in discovered.items():
            if len(records) >= budget:
                break
            url = "{}{}".format(self._settings.base_url, meta["path"])
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except JobsNepalFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("jobsnepal job page {} failed: {}", job_id, exc)
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
            raise JobsNepalResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("jobsnepal: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

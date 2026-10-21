"""Fetches raw postings from Shine.com (India).

Plain HTTP -- no browser. The site is server-rendered HTML with JSON-LD
on detail pages, so urllib is sufficient.

Measured 2026-10-20:

  * **Listing** ``/job-search/jobs-in-india`` returns 40 job cards per
    page, each shaped ``/jobs/<slug>/<company>/<numeric_id>``.
  * **Pagination** appends ``-N`` to the path: ``india-jobs-2``,
    ``india-jobs-3``, etc. Each page adds new ids with no overlap.
  * **Detail pages** carry a top-level JSON-LD ``JobPosting`` block.
  * No ``__NEXT_DATA__`` -- the Next.js app ships data in schema.org
    JSON-LD.
  * Not Cloudflare-walled from datacenter IPs (measured: HTTP 200 with
    full markup from this client).

robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

from loguru import logger

from .config import ShineSettings
from .exceptions import ShineFetchError, ShineResponseError

#: Extracts the numeric job id from a detail URL like
#: /jobs/revenue-assurance/airtel-india/19525849
_JOB_ID_RE = re.compile(r"/jobs/[^/]+/[^/]+/(\d+)")

#: Extracts job-card links from listing HTML.
_LINK_RE = re.compile(r'href="(/jobs/[^/]+/[^/]+/\d+)"')


class _LinkExtractor(HTMLParser):
    """Pulls /jobs/<slug>/<company>/<id> links out of listing markup."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and _JOB_ID_RE.search(href):
            self.links.append(href)


class ShineClient:
    """Fetches postings from Shine.com using plain HTTP."""

    def __init__(self, settings: ShineSettings | None = None) -> None:
        self._settings = settings or ShineSettings()

    def _get(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": self._settings.user_agent})
        try:
            with urllib.request.urlopen(
                req, timeout=self._settings.request_timeout_seconds
            ) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise ShineFetchError(f"HTTP request failed for {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        if page <= 1:
            return f"{self._settings.base_url}{self._settings.listing_path}"
        return (
            f"{self._settings.base_url}{self._settings.listing_path}"
            f"-{self._settings.listing_next_suffix + page - 2}"
        )

    def detail_url(self, job_id: str) -> str:
        return f"{self._settings.base_url}/jobs/x/x/{job_id}"

    def _extract_links(self, html: str) -> list[str]:
        parser = _LinkExtractor()
        parser.feed(html)
        seen: list[str] = []
        for link in parser.links:
            if link not in seen:
                seen.append(link)
        return seen

    def fetch_listing_page(self, page: int = 1) -> tuple[str, list[str]]:
        """Render one listing page. Returns ``(html, [job_urls])``."""
        html = self._get(self.listing_url(page))
        links = self._extract_links(html)
        logger.info("shine listing page {}: {} job link(s)", page, len(links))
        return html, links

    def discover_detail_paths(self) -> tuple[list[str], dict[str, str]]:
        found: list[str] = []
        failures: dict[str, str] = {}

        for page in range(1, self._settings.max_pages + 1):
            try:
                _, links = self.fetch_listing_page(page)
            except ShineFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("shine listing page {} failed: {}", page, exc)
                break
            if not links:
                break
            new = 0
            for link in links:
                match = _JOB_ID_RE.search(link)
                if match:
                    job_id = match.group(1)
                    if job_id not in found:
                        found.append(job_id)
                        new += 1
            logger.info("shine page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found and not failures:
            raise ShineResponseError(
                "no postings found. An empty result means the listing markup "
                "changed -- not that the board is empty -- so it is raised "
                "rather than returned empty."
            )
        return found, failures

    def _fetch_many(self, job_ids: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        rendered: dict[str, str] = {}
        failures: dict[str, str] = {}
        for job_id in job_ids:
            url = self.detail_url(job_id)
            last: Exception | None = None
            for attempt in range(1, self._settings.detail_fetch_attempts + 1):
                try:
                    rendered[job_id] = self._get(url)
                    last = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    logger.warning(
                        "shine fetch attempt {}/{} failed for {}: {}",
                        attempt,
                        self._settings.detail_fetch_attempts,
                        job_id,
                        str(exc)[:100],
                    )
                    if attempt < self._settings.detail_fetch_attempts:
                        time.sleep(self._settings.retry_backoff_seconds)
                        continue
            if last is not None:
                failures[job_id] = f"{type(last).__name__}: {str(last)[:120]}"
            time.sleep(self._settings.inter_request_delay_seconds)
        logger.info("shine rendered {} of {} detail page(s)", len(rendered), len(job_ids))
        return rendered, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        selected = discovered[:budget]

        rendered: dict[str, str] = {}
        if selected:
            try:
                rendered, render_failures = self._fetch_many(selected)
            except ShineFetchError as exc:
                failures["browser"] = str(exc)
                logger.error("shine detail fetch unavailable: {}", exc)
            else:
                for job_id in selected:
                    if job_id in render_failures:
                        failures[job_id] = render_failures[job_id]

        records: list[dict] = []
        for job_id in selected:
            html = rendered.get(job_id)
            if html is None:
                failures.setdefault(job_id, "detail page did not render")
            records.append(
                {
                    "job_id": job_id,
                    "html": html,
                    "url": self.detail_url(job_id),
                }
            )

        if not records and not failures:
            raise ShineResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("shine: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

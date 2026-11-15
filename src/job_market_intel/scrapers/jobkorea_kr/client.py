"""HTTP client for Jobkorea search directory and job detail pages."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request

from bs4 import BeautifulSoup
from loguru import logger

from .config import JobkoreaSettings
from .exceptions import JobkoreaNetworkError
from .models import RawJobkoreaJob

_JOB_ID_RE = re.compile(r"/Recruit/GI_Read/(\d+)")


class JobkoreaClient:
    """Client for discovering Jobkorea vacancies and fetching their detail HTML."""

    def __init__(self, settings: JobkoreaSettings | None = None) -> None:
        self.settings = settings or JobkoreaSettings()

    def _fetch_html(self, url: str) -> str:
        """Fetch content over HTTP with User-Agent, Referer, and timeout with retry."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.jobkorea.co.kr/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        last_exc: Exception | None = None
        for attempt in range(1, 3):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                raise JobkoreaNetworkError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                if attempt < 2:
                    logger.warning("Attempt %d for %s failed (%s), retrying...", attempt, url, exc)
                    time.sleep(2.0)
                    continue
                raise JobkoreaNetworkError(f"Network error fetching {url}: {exc}") from exc
            except Exception as exc:
                raise JobkoreaNetworkError(f"Unexpected error fetching {url}: {exc}") from exc
        raise JobkoreaNetworkError(f"Exhausted retries fetching {url}: {last_exc}")

    def fetch_job_urls(
        self,
        max_pages: int | None = None,
        max_jobs: int | None = None,
    ) -> list[tuple[str, str]]:
        """Paginate through directory pages and extract unique (url, job_id) pairs."""
        pages_to_crawl = max_pages or self.settings.max_pages
        target_limit = max_jobs or self.settings.max_jobs_per_run
        discovered: dict[str, str] = {}

        for page in range(1, pages_to_crawl + 1):
            page_url = f"{self.settings.list_url}?Page={page}&menucode=local&localorder=1"
            logger.info("Fetching Jobkorea listings page {} from {}", page, page_url)
            try:
                html = self._fetch_html(page_url)
            except JobkoreaNetworkError as exc:
                logger.warning("Failed to fetch listings page {}: {}", page, exc)
                break

            soup = BeautifulSoup(html, "html.parser")
            page_links = 0
            for a in soup.find_all("a", href=True):
                match = _JOB_ID_RE.search(a["href"])
                if match:
                    job_id = match.group(1)
                    if job_id not in discovered:
                        detail_url = f"{self.settings.base_url}/Recruit/GI_Read/{job_id}"
                        discovered[job_id] = detail_url
                        page_links += 1

            logger.info(
                "Found {} new job URLs on page {} (total unique: {})",
                page_links,
                page,
                len(discovered),
            )
            if target_limit and len(discovered) >= target_limit:
                break
            if self.settings.rate_limit_delay > 0 and page < pages_to_crawl:
                time.sleep(self.settings.rate_limit_delay)

        logger.info("Discovered {} unique job postings across Jobkorea pages.", len(discovered))
        return [(url, jid) for jid, url in discovered.items()]

    def fetch_job_detail(self, url: str, job_id: str) -> RawJobkoreaJob:
        """Fetch raw HTML for a single Jobkorea vacancy."""
        html = self._fetch_html(url)
        return RawJobkoreaJob(url=url, job_id=job_id, html_content=html)

    def fetch_all_details(
        self,
        job_targets: list[tuple[str, str]],
        max_jobs: int | None = None,
    ) -> list[RawJobkoreaJob]:
        """Fetch detail pages for the discovered targets up to max_jobs."""
        limit = max_jobs or self.settings.max_jobs_per_run
        targets = job_targets[:limit]
        logger.info("Fetching details for {} Jobkorea postings...", len(targets))

        raw_jobs: list[RawJobkoreaJob] = []
        for idx, (url, job_id) in enumerate(targets, 1):
            try:
                raw_job = self.fetch_job_detail(url, job_id)
                raw_jobs.append(raw_job)
            except JobkoreaNetworkError as exc:
                logger.warning("Error fetching detail for {} ({}): {}", job_id, url, exc)

            if self.settings.rate_limit_delay > 0 and idx < len(targets):
                time.sleep(self.settings.rate_limit_delay)

        logger.info("Successfully fetched {} Jobkorea detail pages.", len(raw_jobs))
        return raw_jobs

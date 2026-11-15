"""HTTP client for Job.com.bd listings and detail pages."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request

from bs4 import BeautifulSoup
from loguru import logger

from .config import JobComBdSettings
from .exceptions import JobComBdAPIError
from .models import RawJobComBdJob

_JOB_LINK_RE = re.compile(r"/jobs/[a-zA-Z0-9\-]+-([a-zA-Z0-9]{5,8})$")


class JobComBdClient:
    """Client for discovering Job.com.bd vacancies and downloading their HTML."""

    def __init__(self, settings: JobComBdSettings | None = None) -> None:
        self.settings = settings or JobComBdSettings()

    def _fetch_html(self, url: str) -> str:
        """Fetch content over HTTP with configured User-Agent and timeout with retries."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        last_exc: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                raise JobComBdAPIError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                if attempt < self.settings.max_retries:
                    logger.warning(
                        "Attempt %d/%d for %s failed (%s), retrying in %.1fs...",
                        attempt,
                        self.settings.max_retries,
                        url,
                        exc,
                        self.settings.retry_delay,
                    )
                    time.sleep(self.settings.retry_delay)
                    continue
                raise JobComBdAPIError(f"Network error fetching {url}: {exc}") from exc
            except Exception as exc:
                raise JobComBdAPIError(f"Unexpected error fetching {url}: {exc}") from exc
        raise JobComBdAPIError(f"Exhausted retries fetching {url}: {last_exc}")

    def fetch_job_urls(self, max_pages: int | None = None) -> list[tuple[str, str]]:
        """Paginate through directory pages and extract unique (url, job_id) pairs."""
        pages_to_crawl = max_pages or self.settings.max_pages
        discovered: dict[str, str] = {}

        for page in range(1, pages_to_crawl + 1):
            page_url = f"{self.settings.jobs_url}?page={page}"
            logger.info("Fetching Job.com.bd listings page {} from {}", page, page_url)
            try:
                html_doc = self._fetch_html(page_url)
            except JobComBdAPIError as exc:
                logger.warning("Failed to fetch listings page {}: {}", page, exc)
                break

            soup = BeautifulSoup(html_doc, "html.parser")
            found_this_page = 0
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                m = _JOB_LINK_RE.search(href)
                if m:
                    job_id = m.group(1)
                    if job_id not in discovered:
                        full_url = href if href.startswith("http") else f"{self.settings.base_url}{href}"
                        discovered[job_id] = full_url
                        found_this_page += 1

            logger.info("Found {} new job URLs on page {} (total unique: {})", found_this_page, page, len(discovered))
            if found_this_page == 0:
                logger.info("No further job URLs discovered on page {}. Stopping pagination.", page)
                break
            if self.settings.rate_limit_delay > 0:
                time.sleep(self.settings.rate_limit_delay)

        logger.info("Discovered {} unique job postings across Job.com.bd pages.", len(discovered))
        return [(url, jid) for jid, url in discovered.items()]

    def fetch_job_detail(self, url: str, job_id: str) -> RawJobComBdJob | None:
        """Fetch detail page HTML for a single job."""
        try:
            html_doc = self._fetch_html(url)
            return RawJobComBdJob(
                url=url,
                job_id=job_id,
                html_content=html_doc,
            )
        except JobComBdAPIError as exc:
            logger.warning("Failed to fetch Job.com.bd detail page {}: {}", url, exc)
            return None

    def fetch_all_details(
        self, items: list[tuple[str, str]]
    ) -> list[RawJobComBdJob]:
        """Fetch detail pages for a batch of jobs with rate limiting."""
        raw_jobs: list[RawJobComBdJob] = []
        logger.info("Fetching details for {} Job.com.bd postings...", len(items))
        for idx, (url, jid) in enumerate(items, 1):
            raw = self.fetch_job_detail(url, jid)
            if raw is not None:
                raw_jobs.append(raw)
            if self.settings.rate_limit_delay > 0 and idx < len(items):
                time.sleep(self.settings.rate_limit_delay)
        logger.info("Successfully fetched {} Job.com.bd detail pages.", len(raw_jobs))
        return raw_jobs

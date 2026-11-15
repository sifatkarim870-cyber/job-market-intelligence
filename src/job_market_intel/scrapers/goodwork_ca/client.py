"""HTTP client for GoodWork (Canada) job listings and detail pages."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request

from loguru import logger

from .config import GoodworkSettings
from .exceptions import GoodworkAPIError
from .models import RawGoodworkJob

_JOB_LINK_RE = re.compile(r'href=["\'](/jobs/[a-zA-Z0-9\-]+-([0-9]{4,7}))["\']')


class GoodworkClient:
    """Client for discovering GoodWork postings and downloading their pages."""

    def __init__(self, settings: GoodworkSettings | None = None) -> None:
        self.settings = settings or GoodworkSettings()

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML content with standard browser headers."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise GoodworkAPIError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise GoodworkAPIError(f"Network error fetching {url}: {exc.reason}") from exc
        except Exception as exc:
            raise GoodworkAPIError(f"Unexpected error fetching {url}: {exc}") from exc

    def fetch_job_urls(self) -> list[tuple[str, str]]:
        """Fetch the /jobs directory and extract unique (full_url, job_id) pairs."""
        logger.info("Fetching GoodWork job listings from {}", self.settings.list_url)
        html_doc = self._fetch_html(self.settings.list_url)

        matches = _JOB_LINK_RE.findall(html_doc)
        discovered: dict[str, str] = {}
        for path, jid in matches:
            if jid not in discovered:
                full_url = f"{self.settings.base_url}{path}"
                discovered[jid] = full_url

        logger.info("Discovered {} unique job postings on GoodWork.", len(discovered))
        return [(url, jid) for jid, url in discovered.items()]

    def fetch_job_detail(self, url: str, job_id: str) -> RawGoodworkJob | None:
        """Fetch detail page HTML for a single job."""
        try:
            html_doc = self._fetch_html(url)
            return RawGoodworkJob(
                url=url,
                job_id=job_id,
                html_content=html_doc,
            )
        except GoodworkAPIError as exc:
            logger.warning("Failed to fetch GoodWork detail page {}: {}", url, exc)
            return None

    def fetch_all_details(
        self, items: list[tuple[str, str]]
    ) -> list[RawGoodworkJob]:
        """Fetch detail pages for a batch of jobs with rate limiting."""
        raw_jobs: list[RawGoodworkJob] = []
        logger.info("Fetching details for {} GoodWork postings...", len(items))
        for idx, (url, jid) in enumerate(items, 1):
            raw = self.fetch_job_detail(url, jid)
            if raw is not None:
                raw_jobs.append(raw)
            if self.settings.rate_limit_delay > 0 and idx < len(items):
                time.sleep(self.settings.rate_limit_delay)
        logger.info("Successfully fetched {} GoodWork detail pages.", len(raw_jobs))
        return raw_jobs

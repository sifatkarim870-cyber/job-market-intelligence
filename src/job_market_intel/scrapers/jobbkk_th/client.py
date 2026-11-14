"""HTTP client for JobBKK (Thailand) listings and detail pages."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from loguru import logger

from .config import JobbkkSettings
from .exceptions import JobbkkAPIError
from .models import RawJobbkkJob

_DETAIL_LINK_RE = re.compile(r'/jobs/(?:detail|detailurgent)/([0-9]+)/([0-9]+)')
_JSON_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)


class JobbkkClient:
    """Client for querying JobBKK listing pagination and detail pages."""

    def __init__(self, settings: JobbkkSettings | None = None) -> None:
        self.settings = settings or JobbkkSettings()

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML content from a URL."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise JobbkkAPIError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise JobbkkAPIError(f"Network error fetching {url}: {exc.reason}") from exc
        except Exception as exc:
            raise JobbkkAPIError(f"Unexpected error fetching {url}: {exc}") from exc

    def fetch_job_urls(self, max_pages: int | None = None) -> list[tuple[str, str, str]]:
        """Paginates listing pages to discover unique (url, emp_id, job_id) tuples."""
        pages = max_pages or self.settings.max_pages
        discovered: dict[str, tuple[str, str, str]] = {}

        for page in range(1, pages + 1):
            url = self.settings.list_url_template.format(page=page)
            logger.info("Fetching JobBKK listing page {}: {}", page, url)
            try:
                html_doc = self._fetch_html(url)
            except JobbkkAPIError as exc:
                logger.warning("Failed to fetch listing page {}: {}", page, exc)
                break

            matches = _DETAIL_LINK_RE.findall(html_doc)
            logger.info("Page {} returned {} detail link matches.", page, len(matches))
            for emp_id, jid in matches:
                canonical_path = f"/jobs/detail/{emp_id}/{jid}"
                full_url = f"{self.settings.base_url}{canonical_path}"
                if jid not in discovered:
                    discovered[jid] = (full_url, emp_id, jid)

            if not matches:
                break
            if len(discovered) >= self.settings.max_jobs_per_run:
                break
            if self.settings.rate_limit_delay > 0:
                time.sleep(self.settings.rate_limit_delay)

        results = list(discovered.values())
        logger.info("Discovered {} unique JobBKK postings across pagination.", len(results))
        return results

    def fetch_job_detail(self, url: str, emp_id: str, job_id: str) -> RawJobbkkJob | None:
        """Fetch detail page HTML and parse its Schema.org JobPosting JSON-LD."""
        try:
            html_doc = self._fetch_html(url)
        except JobbkkAPIError as exc:
            logger.warning("Failed to fetch JobBKK detail page {}: {}", url, exc)
            return None

        # Look for JobPosting in JSON-LD
        blocks = _JSON_LD_RE.findall(html_doc)
        job_ld: dict[str, Any] = {}
        for block in blocks:
            try:
                data = json.loads(block)
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    job_ld = data
                    break
            except Exception:
                continue

        if not job_ld:
            logger.warning("No JobPosting JSON-LD found at {}", url)
            return None

        # Optional HTML title
        title_match = re.search(r'<title>(.*?)</title>', html_doc)
        html_title = title_match.group(1).strip() if title_match else None

        return RawJobbkkJob(
            url=url,
            emp_id=emp_id,
            job_id=job_id,
            json_ld=job_ld,
            html_title=html_title,
        )

    def fetch_all_details(
        self, items: list[tuple[str, str, str]]
    ) -> list[RawJobbkkJob]:
        """Fetch full details for a batch of jobs with rate limiting."""
        raw_jobs: list[RawJobbkkJob] = []
        logger.info("Fetching details for {} JobBKK postings...", len(items))
        for idx, (url, emp_id, jid) in enumerate(items, 1):
            raw = self.fetch_job_detail(url, emp_id, jid)
            if raw is not None:
                raw_jobs.append(raw)
            if self.settings.rate_limit_delay > 0 and idx < len(items):
                time.sleep(self.settings.rate_limit_delay)
        logger.info("Successfully parsed {} JobBKK detail records.", len(raw_jobs))
        return raw_jobs

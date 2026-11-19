"""HTTP client for discovering and fetching JobNet (Myanmar) vacancies."""

from __future__ import annotations

import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

from loguru import logger
from job_market_intel.scrapers.jobnet_mm.config import JobnetSettings
from job_market_intel.scrapers.jobnet_mm.exceptions import JobnetFetchError
from job_market_intel.scrapers.jobnet_mm.models import RawJobnetJob

_JOB_LINK_RE = re.compile(r"/job/([^/?#]+)/(\d+)", re.I)


class JobnetClient:
    """Client for JobNet (www.jobnet.com.mm) job portal."""

    def __init__(self, settings: JobnetSettings | None = None) -> None:
        self.settings = settings or JobnetSettings()
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def _fetch_html(self, url: str) -> str:
        """Fetch raw HTML with retry handling and browser headers."""
        # Percent-encode any non-ASCII characters in the URL path/query
        parsed = urllib.parse.urlparse(url)
        safe_path = urllib.parse.quote(parsed.path, safe="/-_~.!*'();:@&=+$,?#[]%")
        safe_url = parsed._replace(path=safe_path).geturl()
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,my;q=0.8",
            "Referer": "https://www.jobnet.com.mm/",
        }
        req = urllib.request.Request(safe_url, headers=headers)
        last_exc: Exception | None = None

        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(
                    req,
                    context=self.ssl_context,
                    timeout=self.settings.request_timeout,
                ) as resp:
                    data = resp.read()
                    return data.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in (404, 410):
                    raise JobnetFetchError(f"HTTP {exc.code} fetching {url}: {exc}") from exc
                logger.warning("HTTP {} fetching {} (attempt {}/3)", exc.code, url, attempt)
                time.sleep(1.0 * attempt)
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                logger.warning("Network error fetching {} (attempt {}/3): {}", url, attempt, exc)
                time.sleep(1.5 * attempt)
            except Exception as exc:
                raise JobnetFetchError(f"Unexpected error fetching {url}: {exc}") from exc
        raise JobnetFetchError(f"Exhausted retries fetching {url}: {last_exc}")

    def fetch_job_urls(
        self,
        max_pages: int | None = None,
        max_jobs: int | None = None,
    ) -> list[tuple[str, str]]:
        """Paginate through search directory and extract unique (url, job_id) pairs."""
        pages_to_crawl = max_pages or self.settings.max_pages
        target_limit = max_jobs or self.settings.max_jobs_per_run
        discovered: dict[str, str] = {}

        for page in range(1, pages_to_crawl + 1):
            if page == 1:
                page_url = self.settings.search_url
            else:
                page_url = f"{self.settings.search_url}?page={page}"

            logger.info("Fetching JobNet listings page {} from {}", page, page_url)
            try:
                html = self._fetch_html(page_url)
            except JobnetFetchError as exc:
                logger.warning("Failed to fetch listings page {}: {}", page, exc)
                break

            soup = BeautifulSoup(html, "html.parser")
            page_links = 0
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                match = _JOB_LINK_RE.search(href)
                if match:
                    slug = match.group(1)
                    job_id = match.group(2)
                    if job_id not in discovered:
                        if href.startswith("http"):
                            detail_url = href
                        else:
                            detail_url = f"{self.settings.base_url}/job/{slug}/{job_id}"
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

        logger.info("Discovered {} unique job postings across JobNet pages.", len(discovered))
        return [(url, jid) for jid, url in discovered.items()]

    def fetch_job_detail(self, url: str, job_id: str) -> RawJobnetJob:
        """Fetch raw HTML for a single JobNet vacancy."""
        html = self._fetch_html(url)
        return RawJobnetJob(url=url, job_id=job_id, html_content=html)

    def fetch_all_details(self, targets: list[tuple[str, str]]) -> list[RawJobnetJob]:
        """Fetch details for a batch of (url, job_id) targets."""
        results: list[RawJobnetJob] = []
        total = len(targets)
        logger.info("Fetching details for {} JobNet postings...", total)

        for idx, (url, jid) in enumerate(targets, 1):
            try:
                raw_job = self.fetch_job_detail(url, jid)
                results.append(raw_job)
            except JobnetFetchError as exc:
                logger.warning("Failed to fetch detail for job_id={} ({}): {}", jid, url, exc)
            if self.settings.rate_limit_delay > 0 and idx < total:
                time.sleep(self.settings.rate_limit_delay)

        logger.info("Successfully fetched {} JobNet detail pages.", len(results))
        return results

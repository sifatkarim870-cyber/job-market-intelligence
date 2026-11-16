"""HTTP client for discovering and fetching Gallito (Uruguay) vacancies."""

from __future__ import annotations

import re
import ssl
import time
import urllib.error
import urllib.request
from bs4 import BeautifulSoup

from loguru import logger
from job_market_intel.scrapers.gallito_uy.config import GallitoSettings
from job_market_intel.scrapers.gallito_uy.exceptions import GallitoNetworkError
from job_market_intel.scrapers.gallito_uy.models import RawGallitoJob

_ANUNCIO_RE = re.compile(r"/anuncio/([^\"'?#]+)", re.I)


class GallitoClient:
    """Client for Gallito (trabajo.gallito.com.uy) job portal."""

    def __init__(self, settings: GallitoSettings | None = None) -> None:
        self.settings = settings or GallitoSettings()
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def _fetch_html(self, url: str) -> str:
        """Fetch raw HTML with retry handling and browser headers."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-UY,es;q=0.9,en;q=0.8",
            "Referer": "https://trabajo.gallito.com.uy/",
        }
        req = urllib.request.Request(url, headers=headers)
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
                    raise GallitoNetworkError(f"HTTP {exc.code} fetching {url}: {exc}") from exc
                logger.warning("HTTP {} fetching {} (attempt {}/3)", exc.code, url, attempt)
                time.sleep(1.0 * attempt)
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                logger.warning("Network error fetching {} (attempt {}/3): {}", url, attempt, exc)
                time.sleep(1.5 * attempt)
            except Exception as exc:
                raise GallitoNetworkError(f"Unexpected error fetching {url}: {exc}") from exc
        raise GallitoNetworkError(f"Exhausted retries fetching {url}: {last_exc}")

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
                page_url = f"{self.settings.search_url}/page/{page}"

            logger.info("Fetching Gallito listings page {} from {}", page, page_url)
            try:
                html = self._fetch_html(page_url)
            except GallitoNetworkError as exc:
                logger.warning("Failed to fetch listings page {}: {}", page, exc)
                break

            soup = BeautifulSoup(html, "html.parser")
            page_links = 0
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                match = _ANUNCIO_RE.search(href)
                if match:
                    path_segment = match.group(1).rstrip("/")
                    parts = path_segment.split("-")
                    job_id = parts[-1] if len(parts) > 1 else path_segment
                    if job_id not in discovered:
                        if href.startswith("http"):
                            detail_url = href
                        else:
                            detail_url = f"{self.settings.base_url}/anuncio/{path_segment}"
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

        logger.info("Discovered {} unique job postings across Gallito pages.", len(discovered))
        return [(url, jid) for jid, url in discovered.items()]

    def fetch_job_detail(self, url: str, job_id: str) -> RawGallitoJob:
        """Fetch raw HTML for a single Gallito vacancy."""
        html = self._fetch_html(url)
        return RawGallitoJob(url=url, job_id=job_id, html_content=html)

    def fetch_all_details(self, targets: list[tuple[str, str]]) -> list[RawGallitoJob]:
        """Fetch details for a batch of (url, job_id) targets."""
        results: list[RawGallitoJob] = []
        total = len(targets)
        logger.info("Fetching details for {} Gallito postings...", total)

        for idx, (url, jid) in enumerate(targets, 1):
            try:
                raw_job = self.fetch_job_detail(url, jid)
                results.append(raw_job)
            except GallitoNetworkError as exc:
                logger.warning("Failed to fetch detail for job_id={} ({}): {}", jid, url, exc)
            if self.settings.rate_limit_delay > 0 and idx < total:
                time.sleep(self.settings.rate_limit_delay)

        logger.info("Successfully fetched {} Gallito detail pages.", len(results))
        return results

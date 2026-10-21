"""Fetches raw postings using the generic HTML scraper framework.

Uses plain HTTP (requests) + CSS selectors configured per site. No browser needed.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

from .config import HtmlScraperSettings, SiteConfig, load_site_config
from .exceptions import HtmlScraperFetchError, HtmlScraperResponseError


def _extract_attr(element, attr: str) -> str | None:
    """Extract an attribute value from a BeautifulSoup element."""
    if element is None:
        return None
    val = element.get(attr)
    return val.strip() if val else None


def _extract_text(element) -> str | None:
    """Extract cleaned text from a BeautifulSoup element."""
    if element is None:
        return None
    text = element.get_text(" ", strip=True)
    return text.strip() if text else None


class HtmlScraperClient:
    """Fetches postings using plain HTTP and CSS selectors."""

    def __init__(
        self,
        source_code: str,
        settings: HtmlScraperSettings | None = None,
        site_config: SiteConfig | None = None,
    ) -> None:
        self._settings = settings or HtmlScraperSettings()
        self._site_config = site_config or load_site_config(
            source_code, self._settings.sites_dir
        )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._site_config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._site_config.base_url}{self._site_config.listing_path}"
        if page <= 1:
            return base
        page_str = self._site_config.listing_pagination.format(page=page)
        return base + page_str

    def detail_url(self, path_or_id: str) -> str:
        if self._site_config.detail_url_pattern:
            return f"{self._site_config.base_url}{self._site_config.detail_url_pattern.format(id=path_or_id)}"
        return f"{self._site_config.base_url}{path_or_id}"

    def _get(self, url: str) -> str:
        try:
            resp = self._session.get(
                url, timeout=self._site_config.request_timeout_seconds
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            raise HtmlScraperFetchError(f"HTTP request failed for {url}: {exc}") from exc

    def _select(self, soup: BeautifulSoup, selector: str) -> list:
        """Run a CSS selector, returning elements."""
        if not selector:
            return []
        try:
            return soup.select(selector)
        except Exception:
            return []

    def _select_one(self, soup: BeautifulSoup, selector: str):
        """Run a CSS selector, returning the first element."""
        if not selector:
            return None
        try:
            return soup.select_one(selector)
        except Exception:
            return None

    def fetch_listing_page(self, page: int = 1) -> tuple[str, list[dict]]:
        """Fetch one listing page. Returns (html, [job_links_with_titles])."""
        html = self._get(self.listing_url(page))
        soup = BeautifulSoup(html, "html.parser")

        # Find all job links on the page
        link_els = self._select(soup, self._site_config.selectors.job_link)
        jobs = []
        for el in link_els:
            link = _extract_attr(el, "href")
            title = _extract_text(el)
            if link:
                link = urljoin(self._site_config.base_url, link)
                jobs.append({"url": link, "title": title or ""})

        # Deduplicate by URL
        seen = set()
        unique_jobs = []
        for j in jobs:
            if j["url"] not in seen:
                seen.add(j["url"])
                unique_jobs.append(j)

        logger.info(
            "html_scraper listing page {}: {} job link(s)", page, len(unique_jobs)
        )
        return html, unique_jobs

    def discover_detail_paths(self) -> tuple[list[dict], dict[str, str]]:
        """Walk listing pages, collecting detail URLs."""
        found: list[dict] = []
        failures: dict[str, str] = {}
        seen_urls: set[str] = set()

        for page in range(1, self._site_config.max_pages + 1):
            try:
                _, jobs = self.fetch_listing_page(page)
            except HtmlScraperFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("html_scraper listing page {} failed: {}", page, exc)
                break
            if not jobs:
                break
            new = 0
            for job in jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    found.append(job)
                    new += 1
            logger.info(
                "html_scraper page {}: {} new ({} total)", page, new, len(found)
            )
            if len(found) >= self._site_config.max_jobs_per_run:
                break
            time.sleep(self._site_config.inter_request_delay_seconds)

        if not found and not failures:
            raise HtmlScraperResponseError(
                "no postings found. The listing markup may have changed."
            )
        return found, failures

    def fetch_detail(self, url: str) -> str:
        """Fetch one detail page HTML."""
        return self._get(url)

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover and fetch postings."""
        budget = self._site_config.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        selected = discovered[:budget]
        records = []
        for job in selected:
            try:
                html = self.fetch_detail(job["url"])
                records.append(
                    {
                        "job_id": job["url"].rsplit("/", 1)[-1]
                        if self._site_config.id_from_url
                        else job["url"],
                        "html": html,
                        "url": job["url"],
                        "title_hint": job.get("title", ""),
                        "listing_page": None,
                    }
                )
            except HtmlScraperFetchError as exc:
                failures[job["url"]] = str(exc)
                logger.warning("html_scraper detail fetch failed for {}: {}", job["url"], exc)
            time.sleep(self._site_config.inter_request_delay_seconds)

        if not records and not failures:
            raise HtmlScraperResponseError(
                "discovery succeeded but every posting was dropped before fetching."
            )
        logger.info(
            "html_scraper: {} record(s), {} failure(s)", len(records), len(failures)
        )
        return records, failures

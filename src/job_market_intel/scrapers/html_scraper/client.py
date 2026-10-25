"""Fetches raw postings using the generic HTML scraper framework.

Uses plain HTTP (requests) + CSS selectors configured per site. No browser needed.
"""

from __future__ import annotations

import json
import time
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from loguru import logger

from .config import (
    GENERIC_LINK_SELECTOR,
    HtmlScraperSettings,
    SiteConfig,
    load_site_config,
)
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


def _is_offsite_social(url: str) -> bool:
    """Social/profile links are never a posting on the board being scraped."""
    from job_market_intel.validation.html_scraper_quality import OFFSITE_HOSTS

    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == h or host.endswith("." + h) for h in OFFSITE_HOSTS)


def _is_job_url(url: str) -> bool:
    """Heuristic: does this URL look like a job detail page?

    Section URLs are rejected explicitly. Without that, the auto-detect pass
    happily returns ``/job-search/operations-jobs`` and ``/jobs/today/`` --
    category pages that mention "job" and were stored as postings.
    """
    from job_market_intel.validation.html_scraper_quality import (
        SECTION_FRAGMENTS,
        SECTION_SEGMENTS,
        has_job_keyword,
    )

    path = urlparse(url).path.lower()
    if len(path) <= 1:  # just "/"
        return False
    if not has_job_keyword(path):
        return False
    for fragment in SECTION_FRAGMENTS:
        if fragment in path:
            return False
    segments = [s for s in path.split("/") if s]
    last = segments[-1]
    if last in SECTION_SEGMENTS:
        return False
    # "/en/ads/sri-lanka/driver-jobs", "/jobs-in-nepal/marketing-sales-jobs-in-nepal"
    return not (last.endswith(("-jobs", "-job")) or "-jobs-in-" in last)


def _json_ld_job_posting(html: str) -> dict | None:
    """Return the schema.org ``JobPosting`` block embedded in a detail page.

    Boards such as Qatar Living render the visible page as unlabelled layout
    divs but publish the same record in ``<script type="application/ld+json">``.
    The block can be a dict, a list of dicts, or a ``@graph`` container, so all
    three shapes are accepted.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates: list = []
        if isinstance(payload, dict):
            candidates = payload.get("@graph") or [payload]
        elif isinstance(payload, list):
            candidates = payload
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


class _LinkExtractor(HTMLParser):
    """Collect every anchor whose URL looks like a job detail page."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []  # (url, text)
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        self._current_href = dict(attrs).get("href")
        self._text_parts = []

    def handle_data(self, data):
        if self._current_href:
            self._text_parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag != "a" or not self._current_href:
            return
        full_url = urljoin(self.base_url, self._current_href)
        text = " ".join(self._text_parts).strip()
        if _is_job_url(full_url):
            self.links.append((full_url, text))
        self._current_href = None
        self._text_parts = []


def _extract_links_from_html(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract all job-looking links from HTML."""
    parser = _LinkExtractor(base_url)
    parser.feed(html)
    return parser.links


def _response_text(resp: requests.Response) -> str:
    """Decode a response, defaulting undeclared modern pages to UTF-8.

    ikman.lk returns ``Content-Type: text/html`` with no charset and no meta
    charset, so requests falls back to ISO-8859-1 and Sinhala titles arrive as
    mojibake. Override that fallback only when the bytes really are UTF-8, so a
    page that is genuinely Latin-1 is left alone.
    """
    ctype = resp.headers.get("content-type", "").lower()
    if "charset=" not in ctype and (resp.encoding or "").lower() == "iso-8859-1":
        try:
            resp.content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            resp.encoding = "utf-8"
    return resp.text


class HtmlScraperClient:
    """Fetches postings using plain HTTP and CSS selectors."""

    def __init__(
        self,
        source_code: str,
        settings: HtmlScraperSettings | None = None,
        site_config: SiteConfig | None = None,
    ) -> None:
        self._settings = settings or HtmlScraperSettings()
        self._site_config = site_config or load_site_config(source_code, self._settings.sites_dir)
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
            pattern = self._site_config.detail_url_pattern.format(id=path_or_id)
            return f"{self._site_config.base_url}{pattern}"
        return f"{self._site_config.base_url}{path_or_id}"

    def _get(self, url: str) -> str:
        try:
            resp = self._session.get(url, timeout=self._site_config.request_timeout_seconds)
            resp.raise_for_status()
            return _response_text(resp)
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

    @staticmethod
    def _dotted(value: Any, path: str) -> Any:
        """Walk a dotted ``a.b.c`` path through nested dicts."""
        node = value
        for key in path.split("."):
            key = key.strip()
            if not key:
                continue
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    def _jobs_from_payload(self, payload: Any) -> list[dict]:
        """Turn the JSON job list into discovery records with detail URLs."""
        path = self._site_config.listing_json_path.strip()
        template = self._site_config.listing_json_url_template.strip()
        if not path or not template:
            return []

        items = self._dotted(payload, path)
        if not isinstance(items, list):
            logger.warning("html_scraper listing JSON path {} is not a list", path)
            return []

        field = self._site_config.listing_json_id_field.strip() or "id"
        jobs = []
        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = self._dotted(item, field)
            if job_id in (None, ""):
                continue
            url = urljoin(self._site_config.base_url, template.format(id=job_id))
            if _is_offsite_social(url):
                continue
            jobs.append({"url": url, "title": "", "id": job_id})
        return jobs

    def _json_listing_jobs(self, html: str) -> list[dict]:
        """Read a job list out of the listing page's embedded Next.js JSON.

        Next.js boards such as Jobzella render the list client-side but ship
        the same records inside ``<script id="__NEXT_DATA__">``. The CSS link
        selector sees no anchors there, so this opt-in path is the only way to
        discover postings without a browser.
        """
        if not self._site_config.listing_json_path.strip():
            return []

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            logger.warning("html_scraper listing JSON missing (__NEXT_DATA__)")
            return []
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError as exc:
            logger.warning("html_scraper listing JSON is not valid JSON: {}", exc)
            return []

        return self._jobs_from_payload(payload)

    def listing_data_url(self, page: int = 1) -> str:
        """The JSON listing endpoint for a 1-based page number."""
        base = self._site_config.listing_json_url.strip()
        if "{page}" in base:
            return base.format(page=page)
        if page <= 1:
            return base
        pagination = self._site_config.listing_pagination
        if "{offset}" in pagination:
            offset = (page - 1) * self._site_config.listing_page_size
            return base + pagination.format(offset=offset)
        return base + pagination.format(page=page)

    def _json_detail_as_html(self, payload: Any, url: str) -> str:
        """Render mapped JSON fields into the minimal HTML the parser expects.

        EmploiPartner serves its job page only to a browser; the data lives at
        an API endpoint. Rendering the mapped fields keeps the parser,
        quality filter and validator on one path instead of growing a second
        JSON-to-model mapper.
        """
        mapping = self._site_config.detail_json_map
        if not mapping:
            return ""

        def text_of(value: str | list[str]) -> str:
            paths = value if isinstance(value, list) else [value]
            parts = []
            for path in paths:
                found = self._dotted(payload, path)
                if found not in (None, ""):
                    parts.append(str(found))
            return "\n".join(parts)

        title = escape(text_of(mapping.get("title", "")))
        company = escape(text_of(mapping.get("company", "")))
        location = escape(text_of(mapping.get("location", "")))
        description = text_of(mapping.get("description", ""))
        posted_date = escape(text_of(mapping.get("posted_date", "")))
        salary = escape(text_of(mapping.get("salary", "")))
        return (
            "<html><body>"
            f"<h1>{title}</h1>"
            f"<div id='company'>{company}</div>"
            f"<div id='location'>{location}</div>"
            f"<div id='description'>{description}</div>"
            f"<div id='posted_date'>{posted_date}</div>"
            f"<div id='salary'>{salary}</div>"
            f"<a href='{escape(url)}'>apply</a>"
            "</body></html>"
        )

    def _html_listing_jobs(self, html: str, soup: BeautifulSoup) -> list[dict]:
        """Discover links on a server-rendered listing page."""
        jobs: list[dict] = []

        if self._site_config.listing_json_path.strip():
            jobs = self._json_listing_jobs(html)

        # Try configured CSS selector first
        link_els = [] if jobs else self._select(soup, self._site_config.selectors.job_link)
        generic_selector = self._site_config.selectors.job_link.strip() == GENERIC_LINK_SELECTOR
        for el in link_els:
            link = _extract_attr(el, "href")
            title = _extract_text(el)
            if link:
                link = urljoin(self._site_config.base_url, link)
                if _is_offsite_social(link):
                    continue
                # Every auto-generated config carries the same guess
                # ("a[href*='/job/']..."), and on most sites it matches the
                # navigation (/careers, /vacancy-list). A guess does not get to
                # skip the URL test that auto-detection must pass.
                if generic_selector and not _is_job_url(link):
                    continue
                jobs.append({"url": link, "title": title or ""})

        # If selector found nothing, auto-extract all job-looking links
        if not jobs:
            raw_links = _extract_links_from_html(html, self._site_config.base_url)
            jobs = [{"url": u, "title": t} for u, t in raw_links if not _is_offsite_social(u)]
        return jobs

    def fetch_listing_page(self, page: int = 1) -> tuple[str, list[dict]]:
        """Fetch one listing page. Returns (html, [job_links_with_titles])."""
        if self._site_config.listing_json_url.strip():
            html = self._get(self.listing_data_url(page))
            try:
                payload = json.loads(html)
            except json.JSONDecodeError as exc:
                raise HtmlScraperResponseError(
                    f"listing JSON endpoint returned non-JSON for page {page}: {exc}"
                ) from exc
            jobs = self._jobs_from_payload(payload)
        else:
            html = self._get(self.listing_url(page))
            soup = BeautifulSoup(html, "html.parser")
            jobs = self._html_listing_jobs(html, soup)

        # Deduplicate by URL
        seen = set()
        unique_jobs = []
        for j in jobs:
            if j["url"] not in seen:
                seen.add(j["url"])
                unique_jobs.append(j)

        logger.info("html_scraper listing page {}: {} job link(s)", page, len(unique_jobs))
        return html, unique_jobs

    def discover_detail_paths(
        self, max_jobs: int | None = None
    ) -> tuple[list[dict], dict[str, str]]:
        """Walk listing pages, collecting detail URLs."""
        found: list[dict] = []
        failures: dict[str, str] = {}
        seen_urls: set[str] = set()
        budget = max_jobs or self._site_config.max_jobs_per_run

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
            logger.info("html_scraper page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= budget:
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
        discovered, failures = self.discover_detail_paths(budget)

        selected = discovered[:budget]
        records = []
        for job in selected:
            try:
                if self._site_config.detail_json_url.strip():
                    job_id = job.get("id") or job["url"].rsplit("/", 1)[-1]
                    detail_url = self._site_config.detail_json_url.format(id=job_id)
                    try:
                        payload = json.loads(self._get(detail_url))
                    except json.JSONDecodeError as exc:
                        raise HtmlScraperFetchError(
                            f"detail JSON endpoint returned non-JSON for {detail_url}: {exc}"
                        ) from exc
                    html = self._json_detail_as_html(payload, job["url"])
                    if not html:
                        raise HtmlScraperFetchError(
                            f"detail_json_map is empty for {self._site_config.source_code}"
                        )
                elif self._site_config.detail_json_ld:
                    page = self.fetch_detail(job["url"])
                    payload = _json_ld_job_posting(page)
                    if payload is None:
                        raise HtmlScraperFetchError(f"no JobPosting JSON-LD on {job['url']}")
                    html = self._json_detail_as_html(payload, job["url"])
                    if not html:
                        raise HtmlScraperFetchError(
                            f"detail_json_map is empty for {self._site_config.source_code}"
                        )
                else:
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
        logger.info("html_scraper: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

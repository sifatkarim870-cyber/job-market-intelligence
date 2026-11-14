"""HTTP client for FINN.no (Norway)."""
from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import FinnNoSettings
from .exceptions import FinnNoFetchError
from .models import RawFinnNoJob

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,no;q=0.8",
}

_AD_LINK_RE = re.compile(r'href=["\'](https://www\.finn\.no/job/ad/(\d+))["\']')
_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


class FinnNoClient:
    """Fetches job listings and details from FINN.no."""

    def __init__(self, settings: FinnNoSettings | None = None) -> None:
        self._s = settings or FinnNoSettings()
        self._ssl_ctx = ssl.create_default_context()

    def _get_html(self, url: str) -> str:
        """Fetch raw HTML string from a URL."""
        req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
        try:
            with urllib.request.urlopen(
                req, context=self._ssl_ctx, timeout=self._s.request_timeout
            ) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise FinnNoFetchError(f"GET {url} failed: {exc}") from exc

    def fetch_ad_links(self, max_links: int = 60) -> list[tuple[str, str]]:
        """
        Paginates through search listings to collect up to max_links (url, job_id) pairs.
        """
        collected: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        page = 1

        while len(collected) < max_links and page <= 10:
            url = f"{self._s.search_url}?page={page}" if page > 1 else self._s.search_url
            logger.info("Fetching FINN.no search page %d: %s", page, url)
            try:
                html = self._get_html(url)
            except FinnNoFetchError as exc:
                logger.warning("Failed fetching search page %d: %s", page, exc)
                break

            matches = _AD_LINK_RE.findall(html)
            if not matches:
                logger.info("No more job links found on page %d", page)
                break

            new_count = 0
            for ad_url, ad_id in matches:
                if ad_id not in seen_ids:
                    seen_ids.add(ad_id)
                    collected.append((ad_url, ad_id))
                    new_count += 1
                    if len(collected) >= max_links:
                        break

            logger.info("Page %d yielded %d new ads (total %d)", page, new_count, len(collected))
            page += 1

        return collected

    def fetch_job_detail(self, ad_url: str, job_id: str) -> RawFinnNoJob | None:
        """Fetch detail page and extract JobPosting JSON-LD."""
        try:
            html = self._get_html(ad_url)
        except FinnNoFetchError as exc:
            logger.warning("Could not fetch detail %s: %s", ad_url, exc)
            return None

        # Extract JobPosting from ld+json
        job_json: dict[str, Any] = {}
        for block in _LD_JSON_RE.findall(html):
            try:
                data = json.loads(block)
                # Handle single-key wrapper: {"script:ld+json": { ... }}
                if isinstance(data, dict) and "script:ld+json" in data:
                    data = data["script:ld+json"]

                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    job_json = data
                    break
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            job_json = item
                            break
                    if job_json:
                        break
            except Exception:
                continue

        return RawFinnNoJob(
            job_id=job_id,
            url=ad_url,
            json_ld=job_json,
            raw_html=html,
        )

    def fetch_all_jobs(self, links: list[tuple[str, str]]) -> list[RawFinnNoJob]:
        """Fetch multiple job details concurrently."""
        jobs: list[RawFinnNoJob] = []
        logger.info(
            "Fetching %d detail pages concurrently (workers=%d) …",
            len(links),
            self._s.detail_concurrency,
        )
        with ThreadPoolExecutor(max_workers=self._s.detail_concurrency) as pool:
            future_to_id = {
                pool.submit(self.fetch_job_detail, ad_url, ad_id): ad_id
                for ad_url, ad_id in links
            }
            for future in as_completed(future_to_id):
                job = future.result()
                if job and job.json_ld:
                    jobs.append(job)
        return jobs

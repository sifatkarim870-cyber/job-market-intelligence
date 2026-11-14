"""HTTP client for Vrabotuvanje (North Macedonia)."""
from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import VrabotuvanjeMkSettings
from .exceptions import VrabotuvanjeMkFetchError
from .models import RawVrabotuvanjeMkJob

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "mk,en;q=0.9,en-US;q=0.8",
}

_JOB_PATH_RE = re.compile(r'href=["\'](/rabota/([0-9a-fA-F-]+)/([^"\'?#]+))')
_NUXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


def _deserialize_nuxt_data(raw_data: list[Any]) -> dict[str, Any]:
    """
    Extract the main job dictionary from a Nuxt 3 flattened state list.
    """
    seen: set[int] = set()

    def resolve(val: Any, depth: int = 0) -> Any:
        if depth > 10:
            return val
        if isinstance(val, int) and 0 <= val < len(raw_data):
            if val in seen:
                return raw_data[val]
            target = raw_data[val]
            if isinstance(target, (str, float, bool)) or target is None:
                return target
            if isinstance(target, list):
                seen.add(val)
                res = [resolve(x, depth + 1) for x in target]
                seen.remove(val)
                return res
            if isinstance(target, dict):
                seen.add(val)
                res = {k: resolve(v, depth + 1) for k, v in target.items()}
                seen.remove(val)
                return res
        return val

    for item in raw_data:
        if isinstance(item, dict) and "title" in item and ("description" in item or "requirements" in item or "slug" in item):
            resolved = {k: resolve(v) for k, v in item.items()}
            return resolved

    return {}


class VrabotuvanjeMkClient:
    """Fetches job listings and details from Vrabotuvanje.com.mk (North Macedonia)."""

    def __init__(self, settings: VrabotuvanjeMkSettings | None = None) -> None:
        self._s = settings or VrabotuvanjeMkSettings()
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
            raise VrabotuvanjeMkFetchError(f"GET {url} failed: {exc}") from exc

    def fetch_job_links(self, max_links: int = 60) -> list[tuple[str, str, str]]:
        """
        Gathers job links from homepage and jobs directory up to max_links.
        """
        collected: list[tuple[str, str, str]] = []
        seen_uuids: set[str] = set()

        seed_urls = [self._s.base_url, self._s.jobs_url]

        for url in seed_urls:
            if len(collected) >= max_links:
                break
            logger.info("Fetching Vrabotuvanje links from %s", url)
            try:
                html = self._get_html(url)
            except VrabotuvanjeMkFetchError as exc:
                logger.warning("Failed fetching %s: %s", url, exc)
                continue

            matches = _JOB_PATH_RE.findall(html)
            new_count = 0
            for path, uuid, slug in matches:
                if uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    full_url = f"{self._s.base_url}{path}"
                    collected.append((full_url, uuid, slug))
                    new_count += 1
                    if len(collected) >= max_links:
                        break

            logger.info("%s yielded %d new ads (total %d)", url, new_count, len(collected))

        return collected

    def fetch_job_detail(self, full_url: str, uuid: str, slug: str) -> RawVrabotuvanjeMkJob | None:
        """Fetch detail page and extract job data from __NUXT_DATA__."""
        try:
            html = self._get_html(full_url)
        except VrabotuvanjeMkFetchError as exc:
            logger.warning("Could not fetch detail %s: %s", full_url, exc)
            return None

        job_data: dict[str, Any] = {}
        nuxt_matches = _NUXT_DATA_RE.findall(html)
        if nuxt_matches:
            try:
                raw_list = json.loads(nuxt_matches[0])
                if isinstance(raw_list, list):
                    job_data = _deserialize_nuxt_data(raw_list)
            except Exception as exc:
                logger.debug("Nuxt data deserialization failed for %s: %s", uuid, exc)

        return RawVrabotuvanjeMkJob(
            uuid=uuid,
            slug=slug,
            url=full_url,
            data=job_data,
            raw_html=html,
        )

    def fetch_all_jobs(self, links: list[tuple[str, str, str]]) -> list[RawVrabotuvanjeMkJob]:
        """Fetch multiple job details concurrently."""
        jobs: list[RawVrabotuvanjeMkJob] = []
        logger.info(
            "Fetching %d detail pages concurrently (workers=%d) …",
            len(links),
            self._s.detail_concurrency,
        )
        with ThreadPoolExecutor(max_workers=self._s.detail_concurrency) as pool:
            future_to_job = {
                pool.submit(self.fetch_job_detail, url, uuid, slug): uuid
                for url, uuid, slug in links
            }
            for future in as_completed(future_to_job):
                job = future.result()
                if job and (job.data or job.raw_html):
                    jobs.append(job)
        return jobs

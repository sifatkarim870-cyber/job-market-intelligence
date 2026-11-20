"""Fetches raw ads from L'Express Petites Annonces (Mauritius).

Discovery is the classifieds jobs category ``/c/emplois`` on
``lexpress-petites-annonces.mu``. It is server-rendered and paginates with
``?page={n}``; page 1 is the bare path. Each page carries ~12 ads and the
whole category held 126+ ads across 11+ live pages when measured on
2026-11-21.

Ad links are site-relative (``/annonce/<YYYYMMDD>-<digits>``) and the whole
token after ``/annonce/`` is the stable id.

robots.txt on both hosts is a generic ``*`` group with an empty ``Disallow``,
i.e. allow-all.
"""

from __future__ import annotations

import re
import time

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import LexpressMuSettings
from .exceptions import LexpressMuFetchError, LexpressMuResponseError

#: ``/annonce/20261116-1794825510`` -> the token after ``/annonce/``.
_AD_TOKEN = re.compile(r"/annonce/(\d{8}-\d+)")


class LexpressMuClient:
    """Fetches ads from L'Express Petites Annonces (Mauritius)."""

    def __init__(self, settings: LexpressMuSettings | None = None) -> None:
        self._settings = settings or LexpressMuSettings()

    def _fetch(self, url: str) -> str:
        try:
            return call_with_retry(
                fetch_html,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=float(self._settings.request_timeout_seconds),
                user_agent=self._settings.user_agent,
            )
        except TransientHTTPError as exc:
            raise LexpressMuFetchError(
                f"L'Express Petites Annonces unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise LexpressMuFetchError(f"L'Express Petites Annonces refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for match in _AD_TOKEN.finditer(html):
            token = match.group(1)
            found.setdefault(token, f"/annonce/{token}")
        logger.info("lexpress_mu listing page {}: {} ad(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except LexpressMuFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("lexpress_mu listing page {} failed: {}", page, exc)
                break
            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue
            new = 0
            for token, path in links.items():
                if token not in found:
                    found[token] = {"path": path, "page": page}
                    new += 1
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "lexpress_mu page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise LexpressMuResponseError(
                f"no ads found in {self._settings.max_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result here means "
                "the markup changed -- not that the category is empty -- so it is "
                "raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for token, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except LexpressMuFetchError as exc:
                    failures[token] = str(exc)
                    logger.warning("lexpress_mu ad page {} failed: {}", token, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": token,
                    "html": html,
                    "url": url,
                    "listing_page": meta["page"],
                }
            )

        if not records and not failures:
            raise LexpressMuResponseError(
                "discovery succeeded but every ad was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("lexpress_mu: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

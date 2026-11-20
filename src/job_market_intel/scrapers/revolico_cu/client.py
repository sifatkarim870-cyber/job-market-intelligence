"""Fetches raw ads from Revolico (Cuba).

Discovery is the server-rendered Next.js search page for the employers' board
``/search?category=empleos_&subcategory=empleos-ofertas-de-empleo``. It
paginates with ``?page={n}``; page 1 is the bare path. Each page carries ~100
ads and the board held hundreds of pages when measured on 2026-11-21.

The page embeds its data in ``<script id="__NEXT_DATA__">`` and the ads are the
``AdType:*`` entries of ``props.pageProps.__APOLLO_STATE__``. Ad links are
site-relative ``/item/<slug>-<id>`` and ``<id>`` is the stable id.

robots.txt is a generic ``*`` group that allows everything except a handful of
account/checkout paths, none of which are used here.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import RevolicoCuSettings
from .exceptions import RevolicoCuFetchError, RevolicoCuResponseError

#: The Next.js data island. Non-greedy up to the closing tag.
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def extract_next_data(html: str) -> dict[str, Any] | None:
    """Return the parsed ``__NEXT_DATA__`` JSON, or ``None`` if absent/invalid."""
    if not html:
        return None
    match = _NEXT_DATA.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (ValueError, TypeError):
        return None


def apollo_state(html: str) -> dict[str, Any]:
    """Return ``props.pageProps.__APOLLO_STATE__`` from a page, or ``{}``."""
    data = extract_next_data(html)
    if not data:
        return {}
    state = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__")
    return state if isinstance(state, dict) else {}


class RevolicoCuClient:
    """Fetches ads from Revolico (Cuba)."""

    def __init__(self, settings: RevolicoCuSettings | None = None) -> None:
        self._settings = settings or RevolicoCuSettings()

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
            raise RevolicoCuFetchError(
                f"Revolico unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise RevolicoCuFetchError(f"Revolico refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        base = (
            f"{self._settings.base_url}{self._settings.search_path}"
            f"?category={self._settings.category}&subcategory={self._settings.subcategory}"
        )
        return base if page <= 1 else f"{base}&page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{ad_id: item_path}`` for one search page."""
        html = self._fetch(self.listing_url(page))
        state = apollo_state(html)
        found: dict[str, str] = {}
        for key, value in state.items():
            if not key.startswith("AdType:") or not isinstance(value, dict):
                continue
            ad_id = str(value.get("id") or key.split(":", 1)[1])
            permalink = value.get("permalink")
            if not permalink:
                continue
            path = permalink if str(permalink).startswith("/") else f"/{permalink}"
            found.setdefault(ad_id, str(path).split("?")[0])
        logger.info("revolico_cu listing page {}: {} ad(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except RevolicoCuFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("revolico_cu listing page {} failed: {}", page, exc)
                break
            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue
            new = 0
            for ad_id, path in links.items():
                if ad_id not in found:
                    found[ad_id] = {"path": path, "page": page}
                    new += 1
            short_page = len(links) < self._settings.min_ads_per_page
            logger.info(
                "revolico_cu page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise RevolicoCuResponseError(
                f"no ads found in {self._settings.max_pages} page(s) of "
                f"{self._settings.search_path} ({self._settings.subcategory}). An "
                "empty result here means the markup changed -- not that the board is "
                "empty -- so it is raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for ad_id, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_detail:
                try:
                    html = self._fetch(url)
                except RevolicoCuFetchError as exc:
                    failures[ad_id] = str(exc)
                    logger.warning("revolico_cu item page {} failed: {}", ad_id, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": ad_id,
                    "html": html,
                    "path": meta["path"],
                    "url": url,
                    "listing_page": meta["page"],
                }
            )

        if not records and not failures:
            raise RevolicoCuResponseError(
                "discovery succeeded but every ad was dropped before fetching -- "
                "raised rather than returned empty."
            )
        logger.info("revolico_cu: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

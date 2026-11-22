"""HTTP client for Nationale Vacaturebank (Netherlands).

Discovery and detail both read **server-rendered HTML** on
``www.nationalevacaturebank.nl``. A plain ``requests`` client gets HTTP 403
``Access Denied`` from the DPG edge, so every call speaks through ``curl_cffi``
with a Chrome impersonation profile. A fresh session's first HTML response can
be the "DPG Media Privacy Gate" consent wall; re-requesting the page on the
same session (the first GET sets the ``authId`` cookies) returns the real
content, which is what :meth:`NationaleVacaturebankNlClient._seed_consent`
does.

Discovery is the board's own published ``/vacatures/sitemap.xml``: the scraper
keeps the content-category URLs and walks a rotating window of
``pages_per_run`` of them. robots.txt disallows ``/vacatures/*?page=``, so only
page 1 of each category is read and no query string is ever appended. Ad pages
are ``/vacature/<uuid>/<slug>`` and the UUID is the stable id.

Withdrawn ads answer HTTP 410, or HTTP 200 without a ``JobPosting`` block.
Both are skipped (and counted) rather than treated as scraper failures; a run
that finds *no* live ad at all raises, so a markup change cannot look like a
quiet board.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import NationaleVacaturebankNlSettings
from .exceptions import (
    NationaleVacaturebankNlFetchError,
    NationaleVacaturebankNlResponseError,
)

#: ``/vacature/<uuid>/<slug>``.
_AD_LINK = re.compile(r'href="(/vacature/[0-9a-f-]{36}/[^"?#]+)"')
_JOB_POSTING_MARKER = re.compile(r'"@type"\s*:\s*"JobPosting"')
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_GATE_MARKERS = ("DPG Media Privacy Gate", "privacygate")


class NationaleVacaturebankNlClient:
    """Fetches category pages and ad pages from Nationale Vacaturebank."""

    def __init__(self, settings: NationaleVacaturebankNlSettings | None = None) -> None:
        self._settings = settings or NationaleVacaturebankNlSettings()
        self._session: curl_requests.Session | None = None

    # -- session / transport ---------------------------------------------

    def _new_session(self) -> curl_requests.Session:
        return curl_requests.Session(
            impersonate=self._settings.impersonate or None,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                "User-Agent": self._settings.user_agent,
            },
        )

    def _request_once(self, url: str) -> tuple[int, str]:
        """One GET, classifying only 5xx/429 as retryable at this layer."""
        try:
            response = self._session.get(
                url,
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=True,
            )
        except (curl_exceptions.RequestException, curl_exceptions.CurlError) as exc:
            raise TransientHTTPError(f"transport failure talking to {url}: {exc}") from exc

        if response.status_code >= 500:
            raise TransientHTTPError(f"{url} returned server error status {response.status_code}")
        if response.status_code == 429:
            raise TransientHTTPError(f"{url} returned 429 (rate limited)")
        if response.status_code >= 400 and response.status_code not in (403, 404, 410):
            raise PermanentHTTPError(
                f"{url} returned client error status {response.status_code}: "
                f"{response.text[:200]!r}"
            )
        return response.status_code, response.text

    def _request(self, url: str) -> tuple[int, str]:
        try:
            return call_with_retry(
                lambda: self._request_once(url),
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise NationaleVacaturebankNlFetchError(
                f"Nationale Vacaturebank unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise NationaleVacaturebankNlFetchError(
                f"Nationale Vacaturebank refused {url}: {exc}"
            ) from exc

    def _seed_consent(self) -> None:
        """Set the session's consent cookies by requesting the jobs home once.

        The first response is sometimes the DPG privacy gate; the same GET a
        second time returns the real page. The gate's ``/privacygate-confirm``
        callback itself answers 403 and is deliberately never called.
        """
        if self._session is None:
            self._session = self._new_session()
        url = f"{self._settings.base_url}/vacatures"
        try:
            _, text = self._request(url)
            if self._looks_like_gate(text):
                time.sleep(self._settings.inter_request_delay_seconds)
                self._request(url)
        except NationaleVacaturebankNlFetchError as exc:
            logger.warning("Nationale Vacaturebank consent seed failed: {}", exc)

    def _ensure_session(self) -> None:
        if self._session is None:
            self._seed_consent()

    @staticmethod
    def _looks_like_gate(text: str) -> bool:
        return len(text) < 25_000 and any(marker in text for marker in _GATE_MARKERS)

    def _fetch_html(self, url: str) -> tuple[int, str]:
        """GET a page, clearing the consent gate once if it appears."""
        self._ensure_session()
        for _ in range(3):
            status, text = self._request(url)
            if status in (403, 404, 410):
                return status, text
            if self._looks_like_gate(text):
                logger.info("Nationale Vacaturebank consent gate at {}; re-seeding", url)
                self._seed_consent()
                continue
            return status, text
        raise NationaleVacaturebankNlFetchError(
            f"{url} kept returning the consent gate after re-seeding"
        )

    # -- discovery -------------------------------------------------------

    def discover_categories(self) -> list[str]:
        """Content-category paths from the board's published sitemap."""
        url = f"{self._settings.base_url}{self._settings.category_sitemap_path}"
        status, text = self._fetch_html(url)
        if status != 200:
            raise NationaleVacaturebankNlResponseError(
                f"category sitemap {url} returned HTTP {status}"
            )

        prefixes = tuple(p.rstrip("/") for p in self._settings.category_path_prefixes)
        paths: list[str] = []
        for loc in _LOC.findall(text):
            path = urlparse(loc.strip()).path.rstrip("/")
            if not path or not any(path.startswith(p) for p in prefixes):
                continue
            # Skip the bare hub pages ("/vacatures/vakgebied"), which only link
            # to the sub-categories.
            if path in prefixes:
                continue
            paths.append(path)
        categories = sorted(set(paths))
        if not categories:
            raise NationaleVacaturebankNlResponseError(
                f"category sitemap {url} listed no content categories; the "
                "sitemap shape changed or the sitemap is empty."
            )
        time.sleep(self._settings.inter_request_delay_seconds)
        logger.info("Nationale Vacaturebank sitemap: {} content categories", len(categories))
        return categories

    def select_categories(self, categories: list[str], *, slot: int | None = None) -> list[str]:
        """A deterministic rotating window of ``pages_per_run`` categories."""
        total = len(categories)
        window = min(self._settings.pages_per_run, total)
        if slot is None:
            slot_seconds = self._settings.rotation_slot_hours * 3600
            slot = int(time.time() // slot_seconds)
        start = (slot * window) % total
        return [categories[(start + offset) % total] for offset in range(window)]

    def fetch_category_links(self, category: str) -> list[str]:
        url = f"{self._settings.base_url}{category}"
        status, text = self._fetch_html(url)
        if status != 200:
            raise NationaleVacaturebankNlResponseError(
                f"category page {url} returned HTTP {status}"
            )
        return list(dict.fromkeys(_AD_LINK.findall(text)))

    def discover_detail_paths(
        self, categories: list[str]
    ) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk the selected categories and merge their ad links round-robin.

        Round-robin rather than category-after-category so a request budget
        that runs out early still samples every selected category instead of
        only the first one.
        """
        per_category: list[tuple[str, list[str]]] = []
        failures: dict[str, str] = {}
        for category in categories:
            try:
                links = self.fetch_category_links(category)
            except NationaleVacaturebankNlFetchError as exc:
                failures[category] = str(exc)
                logger.warning("Nationale Vacaturebank category {} failed: {}", category, exc)
                links = []
            logger.info("Nationale Vacaturebank category {}: {} ad link(s)", category, len(links))
            per_category.append((category, links))
            time.sleep(self._settings.inter_request_delay_seconds)

        found: dict[str, dict] = {}
        while any(group for _, group in per_category):
            for category, group in per_category:
                if not group:
                    continue
                path = group.pop(0)
                job_id = path.split("/")[2]
                found.setdefault(job_id, {"path": path, "category": category})
        return found, failures

    # -- detail ----------------------------------------------------------

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover ad URLs, then fetch each page's HTML.

        Returns ``(records, failures)``. Withdrawn ads (HTTP 404/410 or a page
        with no ``JobPosting`` block) are counted and skipped, not recorded as
        failures. Raises when the run ends with no live ad at all.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}

        categories = self.select_categories(self.discover_categories())
        logger.info("Nationale Vacaturebank categories this run: {}", categories)

        discovered, failures = self.discover_detail_paths(categories)
        if not discovered:
            raise NationaleVacaturebankNlResponseError(
                "Nationale Vacaturebank yielded zero ad links from "
                f"{len(categories)} category page(s). The board published ~99k "
                "ads in its sitemap on 2026-11-22, so an empty result means the "
                "markup changed -- not that the board is empty."
            )

        records: list[dict] = []
        expired = 0
        attempts = 0
        for job_id, meta in discovered.items():
            if len(records) >= budget or attempts >= self._settings.max_detail_attempts:
                break
            attempts += 1
            url = f"{self._settings.base_url}{meta['path']}"
            if not self._settings.fetch_details:
                records.append(
                    {
                        "job_id": job_id,
                        "html": None,
                        "url": url,
                        "listing_category": meta.get("category"),
                    }
                )
                continue
            try:
                status, html = self._fetch_html(url)
            except NationaleVacaturebankNlFetchError as exc:
                failures[job_id] = str(exc)
                logger.warning("Nationale Vacaturebank ad page {} failed: {}", job_id, exc)
                continue
            if status in (404, 410) or not _JOB_POSTING_MARKER.search(html or ""):
                expired += 1
                logger.debug("Nationale Vacaturebank ad {} is withdrawn (HTTP {})", job_id, status)
                continue
            records.append(
                {
                    "job_id": job_id,
                    "html": html,
                    "url": url,
                    "listing_category": meta.get("category"),
                }
            )
            time.sleep(self._settings.inter_request_delay_seconds)

        if not records:
            raise NationaleVacaturebankNlResponseError(
                "Nationale Vacaturebank discovery succeeded but no live ad could "
                f"be fetched ({expired} withdrawn, {len(failures)} failed) -- raised "
                "rather than returned empty."
            )
        logger.info(
            "Nationale Vacaturebank: {} discovered, {} fetched, {} withdrawn, {} failure(s)",
            len(discovered),
            len(records),
            expired,
            len(failures),
        )
        return records, failures

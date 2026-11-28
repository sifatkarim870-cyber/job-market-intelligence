"""Fetches raw postings from work.ua (Ukraine).

Discovery walks the board's own listing (``/jobs/?page=N``, about 14 cards per
page) and collects each card's ``/jobs/<id>/`` link. The ad pages are then
fetched one by one; a page that 404s (an ad removed between listing and detail)
is a dead posting, not a transport failure, so it is recorded and the record is
kept with no detail rather than aborting the run.

Cloudflare is the one non-obvious part. Plain ``requests`` and every
Chrome/Edge ``curl_cffi`` profile are refused with HTTP 403 (work.ua's own
"доступ до сайту тимчасово заборонено" page), while a Safari/Firefox profile is
served normally. The client therefore sends every request through ``curl_cffi``
with ``safari17_0`` and retries with ``firefox133``/``safari18_0`` only when the
primary profile is refused. TLS verification is never disabled.
"""

from __future__ import annotations

import re
import time
from datetime import date

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions
from loguru import logger

from .config import WorkUaSettings
from .exceptions import WorkUaFetchError, WorkUaResponseError
from .models import RawWorkUaJob

_JOB_LINK = re.compile(r"^/jobs/(\d+)/$")
_TOTAL = re.compile(r"([\d\s\u00a0]+)\s*ваканс")
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}


class WorkUaClient:
    """Fetches the work.ua listing pages and the ad pages they point at."""

    def __init__(self, settings: WorkUaSettings | None = None) -> None:
        self._settings = settings or WorkUaSettings()
        self._last_request_at: float | None = None

    # -- transport ---------------------------------------------------------

    def _throttle(self) -> None:
        """Polite gap between any two requests (no Crawl-delay binds the ``*`` group)."""
        if self._last_request_at is None or self._settings.inter_request_delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.inter_request_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get_with_profiles(self, url: str):
        """GET ``url`` through curl_cffi, trying the fallback profiles on HTTP 403."""
        profiles = [self._settings.impersonate, *self._settings.impersonate_fallbacks]
        headers = dict(_HEADERS)
        if self._settings.user_agent:
            headers["User-Agent"] = self._settings.user_agent

        response = None
        for index, profile in enumerate(profiles):
            self._throttle()
            try:
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    headers=headers,
                    timeout=self._settings.request_timeout_seconds,
                )
            finally:
                self._last_request_at = time.monotonic()
            if response.status_code != 403:
                return response
            if index < len(profiles) - 1:
                logger.warning(
                    "work.ua refused profile {} on {} with HTTP 403; trying {}.",
                    profile,
                    url,
                    profiles[index + 1],
                )
        return response

    def _request(self, url: str):
        """One request with bounded backoff; returns the response for any <500.

        Transport errors and 429/5xx answers are retried. A 4xx answer is
        returned to the caller, which knows which status is meaningful for that
        route (a 404 on an ad page means the posting is gone).
        """
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            try:
                response = self._get_with_profiles(url)
            except (curl_exceptions.RequestException, curl_exceptions.CurlError) as exc:
                last_error = exc
                logger.warning(
                    "work.ua request {}/{} failed for {}: {}",
                    attempt,
                    self._settings.max_retry_attempts,
                    url,
                    type(exc).__name__,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue

            if response.status_code in _RETRYABLE_STATUS and (
                attempt < self._settings.max_retry_attempts
            ):
                last_error = WorkUaFetchError(f"HTTP {response.status_code} for {url}")
                logger.warning(
                    "work.ua answered HTTP {} for {} (attempt {}/{})",
                    response.status_code,
                    url,
                    attempt,
                    self._settings.max_retry_attempts,
                )
                time.sleep(wait)
                wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue
            return response

        raise WorkUaFetchError(f"work.ua refused {url}: {last_error}") from last_error

    # -- listing -----------------------------------------------------------

    def listing_url(self, page: int) -> str:
        """The listing URL for ``page`` (1-based)."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        if page <= 1:
            return base + self._settings.listing_pagination.format(page=1)
        return base + self._settings.listing_pagination.format(page=page)

    def fetch_listing_page(self, page: int) -> str:
        """Fetch one listing page's HTML."""
        url = self.listing_url(page)
        response = self._request(url)
        if response.status_code == 404:
            raise WorkUaFetchError(f"work.ua listing page {page} answered HTTP 404")
        if response.status_code != 200:
            raise WorkUaResponseError(
                f"work.ua listing page {page} answered HTTP {response.status_code}"
            )
        return response.text

    def _extract_listing(self, html: str) -> tuple[list[tuple[str, str]], int | None]:
        """Read ``[(job_id, title)]`` and the reported total from one listing page."""
        soup = BeautifulSoup(html, "html.parser")
        found: list[tuple[str, str]] = []
        seen: set[str] = set()

        for card in soup.select("div.job-link"):
            link = card.select_one("h2 a[href]")
            if link is None:
                continue
            href = str(link.get("href") or "").strip()
            match = _JOB_LINK.fullmatch(href)
            if match is None:
                continue
            job_id = match.group(1)
            if job_id in seen:
                continue
            seen.add(job_id)
            found.append((job_id, " ".join(link.get_text(" ", strip=True).split())))

        if not found:
            # The bare /jobs/ path is a JavaScript shell; a real listing page
            # always has the card anchors. Falling back to every matching
            # anchor keeps the parser working if the card class is renamed.
            for link in soup.select("a[href]"):
                href = str(link.get("href") or "").strip()
                match = _JOB_LINK.fullmatch(href)
                if match is None or match.group(1) in seen:
                    continue
                seen.add(match.group(1))
                found.append((match.group(1), " ".join(link.get_text(" ", strip=True).split())))

        total = None
        match = _TOTAL.search(soup.title.get_text(" ", strip=True) if soup.title else html)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                total = int(digits)
        return found, total

    # -- detail ------------------------------------------------------------

    def detail_url(self, job_id: str) -> str:
        return self._settings.detail_url_template.format(
            base_url=self._settings.base_url, job_id=job_id
        )

    def fetch_detail(self, job_id: str) -> str:
        """Fetch one ad page's HTML."""
        url = self.detail_url(job_id)
        response = self._request(url)
        if response.status_code in (404, 410):
            raise WorkUaFetchError(f"HTTP {response.status_code} for {url} (ad removed)")
        if response.status_code != 200:
            raise WorkUaResponseError(f"work.ua ad {job_id} answered HTTP {response.status_code}")
        html = response.text
        if 'id="h1-name"' not in html and "data-company-name" not in html:
            raise WorkUaResponseError(
                f"work.ua ad {job_id} returned HTTP 200 but no ad markup; "
                "the page is probably an interstitial."
            )
        return html

    # -- orchestration -----------------------------------------------------

    def discover(self, max_jobs: int) -> tuple[list[RawWorkUaJob], int, int]:
        """Walk listing pages until ``max_jobs`` ads are collected.

        Returns ``(records, pages_fetched, total_reported)``; the records carry
        no detail HTML yet. ``total_reported`` is the board's own vacancy count
        from page 1 (0 when it could not be read).
        """
        if max_jobs <= 0:
            return [], 0, 0

        records: list[RawWorkUaJob] = []
        seen: set[str] = set()
        pages_fetched = 0
        total_reported = 0
        page = 1

        while len(records) < max_jobs and page <= self._settings.max_pages_scanned:
            html = self.fetch_listing_page(page)
            pages_fetched += 1
            page_items, total = self._extract_listing(html)
            if page == 1 and total:
                total_reported = total
            if not page_items:
                logger.info("work.ua listing page {} carried no ads; stopping.", page)
                break

            new_on_page = 0
            for job_id, title in page_items:
                if job_id in seen:
                    continue
                seen.add(job_id)
                new_on_page += 1
                records.append(
                    RawWorkUaJob(
                        job_id=job_id,
                        url=self.detail_url(job_id),
                        list_position=len(records),
                        listing_title=title,
                        list_total=total_reported or None,
                    )
                )
                if len(records) >= max_jobs:
                    break

            if new_on_page == 0:
                # A repeated page would otherwise loop forever.
                logger.info("work.ua listing page {} repeated earlier ads; stopping.", page)
                break
            page += 1

        return records, pages_fetched, total_reported

    def fetch_raw_jobs(
        self, max_jobs: int | None = None
    ) -> tuple[list[RawWorkUaJob], dict[str, str], int, int]:
        """Read the listing and fetch each ad's detail page.

        Returns ``(raw_jobs, failures, total_reported, pages_fetched)``.
        ``failures`` maps a failed ad URL to the reason; the listing record is
        still returned (with ``detail_html=None``) because it carries a title.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}, 0, 0

        records, pages_fetched, total_reported = self.discover(budget)
        if not records:
            raise WorkUaResponseError(
                "work.ua discovery returned no ads. The board measured about "
                "86,500 vacancies on 2026-11-28, so an empty listing means the "
                "page shape or the network path changed -- not that the board is empty."
            )

        if not self._settings.fetch_details:
            logger.info(
                "work.ua: total={}, pages fetched={}, {} listing rows (details skipped)",
                total_reported,
                pages_fetched,
                len(records),
            )
            return records, {}, total_reported, pages_fetched

        failures: dict[str, str] = {}
        with_detail: list[RawWorkUaJob] = []
        for record in records:
            try:
                html = self.fetch_detail(record.job_id)
            except (WorkUaFetchError, WorkUaResponseError) as exc:
                failures[record.url] = str(exc)
                logger.warning("work.ua ad {} failed: {}", record.job_id, exc)
                with_detail.append(record)
                continue
            with_detail.append(record.model_copy(update={"detail_html": html}))

        logger.info(
            "work.ua: total={}, pages fetched={}, {} rows, {} detail failure(s)",
            total_reported,
            pages_fetched,
            len(with_detail),
            len(failures),
        )
        return with_detail, failures, total_reported, pages_fetched

    @staticmethod
    def today() -> date:
        """Today's local date, exposed for a deterministic test seam."""
        return date.today()

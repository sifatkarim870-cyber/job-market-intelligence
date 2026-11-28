"""Fetches raw postings from the UWV Werk.nl (werk.nl, Netherlands) API.

Discovery is the board's own search API, newest-first and 20 items per page.
The one non-obvious step is the CSRF handshake: ``GET .../api/configuration``
sets an ``XSRF-TOKEN`` cookie that must be echoed back in the ``X-XSRF-TOKEN``
header on every ``POST .../api/search``. Without it the search answers HTTP 400
(Spring's CSRF filter); with the token but a malformed body it answers HTTP 500
(``currentPage`` is 1-based, so ``0`` is a 500 too).

A capped run must still be useful in two directions, so the page window it
takes is not simply "the first N pages":

  * the newest ``fresh_pages`` pages are **always** read, so a run never misses
    what was just posted;
  * the rest of the budget comes from a window that advances one budget-width
    per calendar day (``start_page`` pins it), so the older tail is covered
    over successive runs instead of the same first pages being re-read forever.

A failed detail page is not fatal: the list item already carries the title,
employer, city, hours and contract type, so the parser falls back to those and
the description is simply absent on that one row. The failure is recorded.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import requests
from loguru import logger

from .config import WerkNlSettings
from .exceptions import (
    WerkNlFetchError,
    WerkNlResponseError,
)
from .models import RawWerkNlJob

#: Numbers of digits in a vacancy reference are stable, but nothing leans on it.
_JSON = "application/json"


class WerkNlClient:
    """Fetches the search pages and the detail documents they point at."""

    def __init__(self, settings: WerkNlSettings | None = None) -> None:
        self._settings = settings or WerkNlSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                "Referer": f"{self._settings.base_url}/nl/vacatures",
            }
        )
        self._last_request_at: float | None = None
        self._xsrf_token: str | None = None
        self._bootstrapped = False

    # -- transport ---------------------------------------------------------

    def _throttle(self) -> None:
        """Polite gap between any two requests (robots.txt sets no Crawl-delay)."""
        if self._last_request_at is None or self._settings.inter_request_delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.inter_request_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float,
    ) -> requests.Response:
        """One request with bounded backoff; returns the response for any <500.

        Transport errors and 5xx answers are retried; a 4xx answer is returned
        to the caller, which knows which status is meaningful for that route.
        """
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                if method == "POST":
                    response = self._session.post(url, json=json_body, timeout=timeout)
                else:
                    response = self._session.get(url, timeout=timeout)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Werk.nl request {}/{} failed for {}: {}",
                    attempt,
                    self._settings.max_retry_attempts,
                    url,
                    type(exc).__name__,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue
            finally:
                self._last_request_at = time.monotonic()

            if response.status_code >= 500:
                last_error = WerkNlFetchError(f"HTTP {response.status_code} for {url}")
                logger.warning(
                    "Werk.nl answered HTTP {} for {} (attempt {}/{})",
                    response.status_code,
                    url,
                    attempt,
                    self._settings.max_retry_attempts,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue
            return response

        raise WerkNlFetchError(f"Werk.nl refused {url}: {last_error}") from last_error

    # -- CSRF bootstrap ----------------------------------------------------

    def bootstrap(self, *, force: bool = False) -> None:
        """Read the endpoint map and capture the ``XSRF-TOKEN`` cookie.

        ``GET .../api/configuration`` is the documented CSRF bootstrap: it is
        the first request the Angular app makes and it is what mints the
        ``XSRF-TOKEN`` cookie the search POST must echo.
        """
        if self._bootstrapped and not force:
            return
        response = self._request(
            "GET", self._settings.configuration_url, timeout=self._settings.request_timeout_seconds
        )
        if response.status_code != 200:
            raise WerkNlResponseError(
                f"Werk.nl configuration answered HTTP {response.status_code}; "
                "cannot establish the CSRF token needed for the search API."
            )
        token = self._session.cookies.get("XSRF-TOKEN")
        if not token:
            raise WerkNlResponseError(
                "Werk.nl configuration returned HTTP 200 but set no XSRF-TOKEN cookie; "
                "the CSRF bootstrap changed and the search API cannot be called."
            )
        self._xsrf_token = token
        self._session.headers["X-XSRF-TOKEN"] = token
        self._session.headers["X-Requested-With"] = "XMLHttpRequest"
        self._bootstrapped = True

    # -- search ------------------------------------------------------------

    def search_page(self, page: int) -> dict[str, Any]:
        """Fetch one search page (1-based). Returns the parsed JSON document."""
        self.bootstrap()
        payload = {"keywords": "", "location": "", "currentPage": page}
        for attempt in (1, 2):
            response = self._request(
                "POST",
                self._settings.search_url,
                json_body=payload,
                timeout=self._settings.request_timeout_seconds,
            )
            if response.status_code == 400 and attempt == 1:
                # The CSRF token likely rotated; re-mint once and retry.
                logger.warning("Werk.nl search page {} answered HTTP 400; re-bootstrapping.", page)
                self.bootstrap(force=True)
                continue
            if response.status_code != 200:
                raise WerkNlResponseError(
                    f"Werk.nl search page {page} answered HTTP {response.status_code}; "
                    "the search API rejected the request."
                )
            try:
                document = response.json()
            except ValueError as exc:
                raise WerkNlResponseError(
                    f"Werk.nl search page {page} was not JSON: {exc}"
                ) from exc
            if not isinstance(document, dict) or "items" not in document:
                raise WerkNlResponseError(
                    f"Werk.nl search page {page} carried no 'items' array; the API shape changed."
                )
            return document
        raise WerkNlResponseError(
            f"Werk.nl search page {page} kept answering HTTP 400 after a CSRF refresh."
        )

    # -- detail ------------------------------------------------------------

    def fetch_detail(self, job_id: str) -> dict[str, Any]:
        """Fetch one vacancy's detail document."""
        url = self._settings.detail_url_template.format(job_id=job_id)
        response = self._request("GET", url, timeout=self._settings.request_timeout_seconds)
        if response.status_code in (404, 410):
            raise WerkNlFetchError(f"HTTP {response.status_code} for {url}")
        if response.status_code != 200:
            raise WerkNlFetchError(f"HTTP {response.status_code} for {url}")
        try:
            document = response.json()
        except ValueError as exc:
            raise WerkNlResponseError(f"Werk.nl detail {job_id} was not JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise WerkNlResponseError(f"Werk.nl detail {job_id} was not an object")
        return document

    # -- window selection --------------------------------------------------

    def total_pages(self, total_results: int) -> int:
        """Pages available for ``total_results`` items, capped at the guard."""
        if total_results <= 0:
            return 0
        pages = (total_results + self._settings.page_size - 1) // self._settings.page_size
        return min(pages, self._settings.max_pages_scanned)

    def rotation_offset(self, window_size: int, step: int) -> int:
        """Where the rotating page window starts.

        ``start_page`` pins it. Otherwise it advances ``step`` pages per
        calendar day, so consecutive daily runs tile the tail instead of
        overlapping it.
        """
        if window_size <= 0:
            return 0
        if self._settings.start_page is not None:
            return (self._settings.start_page - 1) % window_size
        step = max(1, step)
        return (date.today().toordinal() * step) % window_size

    def select_pages(self, pages_available: int, budget_pages: int) -> list[int]:
        """The newest ``fresh_pages`` pages plus a rotating slice of the rest."""
        if budget_pages <= 0 or pages_available <= 0:
            return []
        if budget_pages >= pages_available:
            return list(range(1, pages_available + 1))

        fresh_n = min(self._settings.fresh_pages, budget_pages, pages_available)
        chosen = list(range(1, fresh_n + 1))
        tail_budget = budget_pages - fresh_n
        tail_len = pages_available - fresh_n
        if tail_budget > 0 and tail_len > 0:
            start = self.rotation_offset(tail_len, tail_budget)
            chosen.extend((fresh_n + 1) + ((start + i) % tail_len) for i in range(tail_budget))
        return chosen[:budget_pages]

    # -- orchestration -----------------------------------------------------

    @staticmethod
    def _normalise_item(item: dict[str, Any]) -> dict[str, Any]:
        """Keep the raw list item verbatim; only require an id for the URL."""
        return dict(item)

    def _collect_list_records(
        self, first: dict[str, Any], total_results: int, budget: int
    ) -> tuple[list[RawWerkNlJob], int]:
        """Walk the selected search pages and keep up to ``budget`` list items."""
        pages_available = self.total_pages(total_results)
        budget_pages = max(1, (budget + self._settings.page_size - 1) // self._settings.page_size)
        selected_pages = self.select_pages(pages_available, budget_pages)

        records: list[RawWerkNlJob] = []
        seen: set[str] = set()
        pages_fetched = 0

        for page in selected_pages:
            document = first if page == 1 else self.search_page(page)
            pages_fetched += 1
            for item in document.get("items") or []:
                job_id = str(item.get("referenceNumber") or "").strip()
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)
                records.append(
                    RawWerkNlJob(
                        job_id=job_id,
                        url=self._settings.public_job_url_template.format(job_id=job_id),
                        list_position=len(records),
                        list_total=total_results,
                        list_item=self._normalise_item(item),
                    )
                )
                if len(records) >= budget:
                    return records, pages_fetched
        return records, pages_fetched

    def _attach_details(
        self, records: list[RawWerkNlJob]
    ) -> tuple[list[RawWerkNlJob], dict[str, str]]:
        """Fetch each record's detail; keep the list row when one fails."""
        failures: dict[str, str] = {}
        with_detail: list[RawWerkNlJob] = []
        for record in records:
            try:
                detail = self.fetch_detail(record.job_id)
            except (WerkNlFetchError, WerkNlResponseError) as exc:
                failures[record.url] = str(exc)
                logger.warning("Werk.nl detail {} failed: {}", record.job_id, exc)
                with_detail.append(record)
                continue
            with_detail.append(record.model_copy(update={"detail": detail}))
        return with_detail, failures

    def fetch_raw_jobs(
        self, max_jobs: int | None = None
    ) -> tuple[list[RawWerkNlJob], dict[str, str], int, int]:
        """Read the selected search pages and fetch their detail documents.

        Returns ``(raw_jobs, failures, total_results, pages_scanned)``.
        ``failures`` maps a failed detail URL to the reason; the list item is
        still returned as a record (with ``detail=None``) because it carries
        enough fields to be useful.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}, 0, 0

        first = self.search_page(1)
        total_results = int(first.get("totalResults") or 0)
        if total_results <= 0 and not first.get("items"):
            raise WerkNlResponseError(
                "Werk.nl search page 1 returned no items and totalResults=0. "
                "The board measured 281,590 vacancies on 2026-11-28, so an empty "
                "result means the API shape changed -- not that the board is empty."
            )

        records, pages_fetched = self._collect_list_records(first, total_results, budget)
        if not records:
            raise WerkNlResponseError(
                "Werk.nl discovery succeeded but no vacancy was collected -- "
                "raised rather than returned empty."
            )

        if not self._settings.fetch_details:
            logger.info(
                "Werk.nl: total={}, pages fetched={}, {} list rows (details skipped)",
                total_results,
                pages_fetched,
                len(records),
            )
            return records, {}, total_results, pages_fetched

        with_detail, failures = self._attach_details(records)
        logger.info(
            "Werk.nl: total={}, pages fetched={}, {} rows, {} detail failure(s)",
            total_results,
            pages_fetched,
            len(with_detail),
            len(failures),
        )
        return with_detail, failures, total_results, pages_fetched

"""HTTP client for discovering and fetching VDAB vacancies.

Everything here talks to the two robots-ALLOWED ``/rest/vindeenjob/v4/``
endpoints (see ``config.py``). The disallowed ``/api/vindeenjob/`` base and the
Angular ad pages are never requested.

Discovery is the paginated search endpoint, requested newest-first
(``sorteerVeld=DATUM``) and then re-sorted locally by ``eerstePublicatieDatum``
desc, id desc so the window is deterministic even within a single day. A capped
run is not simply "the first N rows": the newest ``fresh_rows`` are always
taken, and the rest of the budget comes from a window that advances one
window-width per calendar day (``start_offset`` pins it), so successive runs
cover the scanned set instead of re-reading the same head forever.

Every request sends the ``vej-key-monitor`` header -- a static public constant
from the site's own JavaScript, without which the API answers HTTP 403 with an
empty body. See ``config.py`` for why it is not a credential.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import requests
from loguru import logger

from .config import VdabSettings
from .exceptions import VdabFetchError, VdabResponseError
from .models import RawVdabJob


def _result_id(item: dict[str, Any]) -> str | None:
    """The numeric vacancy id from a search row, as a string."""
    ident = item.get("id")
    if isinstance(ident, dict):
        value = ident.get("id")
    else:
        value = ident
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class VdabClient:
    """Client for the VDAB (Flanders, Belgium) public vacancy API."""

    def __init__(self, settings: VdabSettings | None = None) -> None:
        self._settings = settings or VdabSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8,fr;q=0.7",
                "Referer": self._settings.base_url + "/vindeenjob/vacatures",
                # Static public front-end constant, not an auth key.
                "vej-key-monitor": self._settings.monitor_key,
            }
        )
        self._last_request_at: float | None = None

    def ad_url(self, job_id: str) -> str:
        """Canonical public ad URL for a vacancy id."""
        return self._settings.ad_url_template.format(job_id=job_id)

    def detail_url(self, job_id: str) -> str:
        """REST detail endpoint URL for a vacancy id."""
        return self._settings.detail_url_template.format(job_id=job_id)

    def _throttle(self) -> None:
        """Keep a polite gap between any two requests."""
        if self._last_request_at is None or self._settings.rate_limit_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.rate_limit_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Send one request with bounded backoff and a polite delay."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds

        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.request(
                    method, url, timeout=self._settings.request_timeout, **kwargs
                )
                if response.status_code in (404, 410):
                    raise VdabFetchError(f"HTTP {response.status_code} fetching {url}")
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "vdab.be request {}/{} failed for {}: {}",
                    attempt,
                    self._settings.max_retry_attempts,
                    url,
                    type(exc).__name__,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
            finally:
                self._last_request_at = time.monotonic()

        raise VdabFetchError(f"vdab.be refused {url}: {last_error}") from last_error

    def search_page(self, page: int) -> dict[str, Any]:
        """Fetch one search page (zero-based) and return its decoded JSON."""
        body = {
            "criteria": {
                "onlineSindsCode": self._settings.online_sinds_code,
                "sorteerVeld": self._settings.sort_field,
            },
            "pagina": page,
            "zoekmodus": self._settings.search_mode,
            "paginaGrootte": self._settings.page_size,
        }
        response = self._request("POST", self._settings.search_url, json=body)
        try:
            payload = response.json()
        except ValueError as exc:
            raise VdabResponseError(
                f"vdab.be search returned non-JSON for page {page}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise VdabResponseError(f"vdab.be search returned {type(payload).__name__}")
        return payload

    def discover(self) -> tuple[list[dict[str, Any]], int]:
        """Return ``(rows, pages_scraped)`` newest-first, deduped by ad id.

        Each row is ``{"job_id": str, "published": str, "listing": {...}}``.
        """
        found: dict[str, dict[str, Any]] = {}
        pages_scraped = 0
        pages_to_walk = self._settings.max_pages

        for page in range(pages_to_walk):
            try:
                payload = self.search_page(page)
            except VdabFetchError as exc:
                logger.warning("vdab.be search page {} failed: {}", page, exc)
                break
            pages_scraped += 1

            results = payload.get("resultaten") or []
            if not results:
                break

            new = 0
            for item in results:
                job_id = _result_id(item)
                if job_id is None or job_id in found:
                    continue
                found[job_id] = {
                    "job_id": job_id,
                    "published": str(item.get("eerstePublicatieDatum") or ""),
                    "listing": item,
                }
                new += 1

            logger.info(
                "vdab.be search page {}: {} new ad(s) ({} total, totaalAantal={})",
                page,
                new,
                len(found),
                payload.get("totaalAantal"),
            )
            if new == 0:
                # A page with nothing new means the pager stopped advancing.
                break

        if not found:
            raise VdabResponseError(
                f"no vacancies discovered across {pages_scraped} page(s) of "
                f"{self._settings.search_url}. An empty result means the request "
                "shape changed -- not that the board is empty -- so it is raised "
                "rather than returned empty."
            )

        rows = list(found.values())
        rows.sort(key=lambda row: (row["published"], int(row["job_id"])), reverse=True)
        logger.info(
            "vdab.be discovered {} unique ad(s) across {} page(s).",
            len(rows),
            pages_scraped,
        )
        return rows, pages_scraped

    def rotation_offset(self, window_size: int, tail_size: int) -> int:
        """Where the rotating tail window starts.

        ``start_offset`` pins it. Otherwise it advances one window-width per
        calendar day, so consecutive daily runs tile the tail instead of
        overlapping it.
        """
        if window_size <= 0:
            return 0
        if self._settings.start_offset is not None:
            return self._settings.start_offset % window_size
        step = max(1, tail_size)
        return (date.today().toordinal() * step) % window_size

    def select_window(self, rows: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
        """The newest ``fresh_rows`` rows plus a rotating slice of the rest."""
        if budget >= len(rows):
            return list(rows)

        fresh_n = min(self._settings.fresh_rows, budget, len(rows))
        chosen = list(rows[:fresh_n])
        tail = list(rows[fresh_n:])
        tail_budget = budget - len(chosen)
        if tail and tail_budget > 0:
            start = self.rotation_offset(len(tail), tail_budget)
            rotated = tail[start:] + tail[:start]
            chosen.extend(rotated[:tail_budget])
        return chosen[:budget]

    def fetch_detail(self, row: dict[str, Any]) -> RawVdabJob:
        """Fetch and return the raw detail payload for one discovered row."""
        job_id = row["job_id"]
        response = self._request("GET", self.detail_url(job_id), params={"preview": "false"})
        try:
            payload = response.json()
        except ValueError as exc:
            raise VdabFetchError(f"vdab.be detail non-JSON for {job_id}: {exc}") from exc
        if not isinstance(payload, dict):
            raise VdabFetchError(f"vdab.be detail for {job_id} is {type(payload).__name__}")
        return RawVdabJob(
            job_id=job_id,
            url=self.ad_url(job_id),
            listing=row.get("listing", {}),
            payload=payload,
        )

    def fetch_raw_jobs(
        self, max_jobs: int | None = None
    ) -> tuple[list[RawVdabJob], list[str], int, int]:
        """Discover the board and fetch the window this run should persist.

        Returns ``(raw_jobs, failed_ids, pages_scraped, discovered_count)``.
        """
        rows, pages_scraped = self.discover()
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        selected = self.select_window(rows, budget)
        logger.info(
            "vdab.be selected {} of {} discovered ad(s) for detail retrieval (budget={}).",
            len(selected),
            len(rows),
            budget,
        )

        raw_jobs: list[RawVdabJob] = []
        failed_ids: list[str] = []
        for row in selected:
            try:
                raw_jobs.append(self.fetch_detail(row))
            except VdabFetchError as exc:
                logger.warning("Failed to fetch detail for id={}: {}", row["job_id"], exc)
                failed_ids.append(row["job_id"])

        logger.info(
            "Fetched {} vdab.be detail payload(s) ({} failed).",
            len(raw_jobs),
            len(failed_ids),
        )
        return raw_jobs, failed_ids, pages_scraped, len(rows)

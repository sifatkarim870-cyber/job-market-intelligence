"""Fetches raw postings from Chiletrabajos (chiletrabajos.cl, Chile).

Discovery is the board's advertised sitemap, a single ``<urlset>`` of
``/trabajo/<slug>-<id>`` URLs in newest-first order. The sitemap is the
whole board, so it is read once per run; the run then fetches at most
``max_jobs_per_run`` ad pages one at a time.

A capped run must still be useful in two directions, so the window it takes
is not simply "the first N sitemap entries":

  * the newest ``fresh_rows`` entries are **always** included, so a run never
    misses what was just posted;
  * the rest of the budget comes from a window that advances one budget-width
    per calendar day (``start_offset`` pins it), so the older tail is covered
    over successive runs instead of the same first page being re-read forever.

A failed ad page is not fatal and is not turned into a half-record: the
sitemap carries only the URL (no title or employer), so the failure is
recorded and the entry is skipped.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests
from loguru import logger

from .config import ChiletrabajosClSettings
from .exceptions import (
    ChiletrabajosClFetchError,
    ChiletrabajosClResponseError,
)
from .models import RawChiletrabajosJob, SitemapEntry

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_JOB_ID = re.compile(r"-(\d+)$")


class ChiletrabajosClClient:
    """Fetches the sitemap and the ad pages it points at."""

    def __init__(self, settings: ChiletrabajosClSettings | None = None) -> None:
        self._settings = settings or ChiletrabajosClSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
            }
        )
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        """Polite gap between any two requests (robots.txt sets no Crawl-delay)."""
        if self._last_request_at is None or self._settings.inter_request_delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.inter_request_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, *, timeout: float) -> requests.Response:
        """GET with bounded exponential backoff; raises ``ChiletrabajosClFetchError``."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=timeout)
                if response.status_code in (404, 410):
                    raise ChiletrabajosClFetchError(f"HTTP {response.status_code} for {url}")
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Chiletrabajos request {}/{} failed for {}: {}",
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
        raise ChiletrabajosClFetchError(
            f"Chiletrabajos refused {url}: {last_error}"
        ) from last_error

    def fetch_sitemap(self) -> str:
        """Download the advertised sitemap, refusing an outsized body."""
        response = self._get(
            self._settings.sitemap_url, timeout=self._settings.sitemap_timeout_seconds
        )
        content = response.content
        if len(content) > self._settings.max_sitemap_bytes:
            raise ChiletrabajosClResponseError(
                f"Chiletrabajos sitemap is {len(content)} bytes, over the "
                f"{self._settings.max_sitemap_bytes}-byte guard. The sitemap format "
                "or host changed; refusing to buffer it silently."
            )
        return content.decode(response.encoding or "utf-8", errors="replace")

    @staticmethod
    def parse_sitemap(xml: str) -> list[SitemapEntry]:
        """Parse a ``<urlset>`` sitemap into ad entries, in document order."""
        if not (xml or "").strip():
            raise ChiletrabajosClResponseError("Chiletrabajos sitemap is empty")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ChiletrabajosClResponseError(
                f"Chiletrabajos sitemap is not well-formed XML: {exc}"
            ) from exc

        root_tag = root.tag.split("}")[-1]
        if root_tag == "sitemapindex":
            raise ChiletrabajosClResponseError(
                "Chiletrabajos sitemap is now a <sitemapindex>, not the single "
                "<urlset> measured on 2026-10-09. Discovery needs a child-sitemap "
                "walk before it can run again."
            )
        if root_tag != "urlset":
            raise ChiletrabajosClResponseError(
                f"Chiletrabajos sitemap root is <{root_tag}>, not <urlset>; "
                "the advertised format changed."
            )

        entries: list[SitemapEntry] = []
        for position, node in enumerate(root.findall(f"{_SITEMAP_NS}url")):
            loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
            if "/trabajo/" not in loc:
                continue
            match = _JOB_ID.search(loc)
            if not match:
                logger.warning("Chiletrabajos sitemap URL has no trailing id: {}", loc)
                continue
            lastmod = (node.findtext(f"{_SITEMAP_NS}lastmod") or "").strip() or None
            entries.append(
                SitemapEntry(
                    job_id=match.group(1),
                    url=loc,
                    lastmod=lastmod,
                    position=position,
                )
            )
        return entries

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

    def select_window(self, entries: list[SitemapEntry], budget: int) -> list[SitemapEntry]:
        """The newest ``fresh_rows`` entries plus a rotating slice of the rest."""
        if budget >= len(entries):
            return entries

        fresh_n = min(self._settings.fresh_rows, budget, len(entries))
        chosen = entries[:fresh_n]
        tail = entries[fresh_n:]
        tail_budget = budget - len(chosen)
        if tail and tail_budget > 0:
            start = self.rotation_offset(len(tail), tail_budget)
            rotated = tail[start:] + tail[:start]
            chosen.extend(rotated[:tail_budget])
        return chosen[:budget]

    def fetch_detail(self, url: str) -> str:
        """Fetch one ad page and return its HTML."""
        response = self._get(url, timeout=self._settings.request_timeout_seconds)
        return response.text

    def fetch_raw_jobs(
        self, max_jobs: int | None = None
    ) -> tuple[list[RawChiletrabajosJob], dict[str, str], int]:
        """Read the sitemap and fetch the selected ad pages.

        Returns ``(raw_jobs, failures, sitemap_entries)``. ``failures`` maps
        a failed URL to the reason; only successfully fetched pages become
        ``RawChiletrabajosJob`` records because the sitemap holds no fallback
        fields.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}, 0

        entries = self.parse_sitemap(self.fetch_sitemap())
        if not entries:
            raise ChiletrabajosClResponseError(
                "Chiletrabajos sitemap parsed to zero /trabajo/ entries. The board "
                "measured 32,993 entries on 2026-10-09, so an empty result means "
                "the sitemap or its markup changed -- not that the board is empty."
            )

        selected = self.select_window(entries, budget)
        failures: dict[str, str] = {}
        records: list[RawChiletrabajosJob] = []

        for entry in selected:
            if not self._settings.fetch_details:
                records.append(
                    RawChiletrabajosJob(
                        job_id=entry.job_id,
                        url=entry.url,
                        sitemap_position=entry.position,
                        sitemap_total=len(entries),
                        lastmod=entry.lastmod,
                    )
                )
                continue
            try:
                html = self.fetch_detail(entry.url)
            except ChiletrabajosClFetchError as exc:
                failures[entry.url] = str(exc)
                logger.warning("Chiletrabajos ad {} failed: {}", entry.job_id, exc)
                continue
            records.append(
                RawChiletrabajosJob(
                    job_id=entry.job_id,
                    url=entry.url,
                    sitemap_position=entry.position,
                    sitemap_total=len(entries),
                    lastmod=entry.lastmod,
                    html_content=html,
                )
            )

        if not records and not failures:
            raise ChiletrabajosClResponseError(
                "Chiletrabajos discovery succeeded but no ad page was fetched -- "
                "raised rather than returned empty."
            )
        logger.info(
            "Chiletrabajos: {} sitemap entr(ies), {} selected, {} fetched, {} failure(s)",
            len(entries),
            len(selected),
            len(records),
            len(failures),
        )
        return records, failures, len(entries)

"""Fetches raw postings from MauKerja (maukerja.my, Malaysia).

Discovery is the board's advertised sitemap chain, measured 2026-11-20:

    /sitemap.xml          sitemapindex, 17 children
      -> /mk_job.xml      sitemapindex, 1 child
         -> /mk_job1.xml  <urlset>, 46,652 job URLs, ~9 MB, newest-first

The walk follows only children whose file name matches ``^mk_job\\d*\\.xml$``,
so the one job sitemap is found while the company, category, blog, salary and
forum sitemaps (and the company-scoped job listings, whose sitemap is
``mk_company_job.xml``) are skipped. A future ``mk_job2.xml`` is picked up
automatically; ``mk_jobsearch``/``mk_company_job`` never match.

A capped run must still be useful in two directions, so the window it takes is
not simply "the first N sitemap entries":

  * the newest ``fresh_rows`` entries are **always** included, so a run never
    misses what was just posted;
  * the rest of the budget comes from a window that advances one budget-width
    per calendar day (``start_offset`` pins it), so the older tail is covered
    over successive runs instead of the same first page being re-read forever.

A failed ad page is not fatal and is not turned into a half-record: the sitemap
carries only the URL (no title or employer), so the failure is recorded and the
entry is skipped.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import urlparse

import requests
from loguru import logger

from .config import MaukerjaMySettings
from .exceptions import MaukerjaMyFetchError, MaukerjaMyResponseError
from .models import RawMaukerjaMyJob, SitemapEntry

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
#: Only these children of a sitemap index are job-ad sets.
_JOB_SITEMAP_NAME = re.compile(r"^mk_job\d*\.xml$")
_JOB_ID = re.compile(r"/job/([A-Za-z0-9]{6,})")


class MaukerjaMyClient:
    """Walks the sitemap chain and fetches the ad pages it points at."""

    def __init__(self, settings: MaukerjaMySettings | None = None) -> None:
        self._settings = settings or MaukerjaMySettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ms-MY,ms;q=0.9,en;q=0.8",
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
        """GET with bounded exponential backoff; raises ``MaukerjaMyFetchError``."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=timeout)
                if response.status_code in (404, 410):
                    raise MaukerjaMyFetchError(f"HTTP {response.status_code} for {url}")
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "MauKerja request {}/{} failed for {}: {}",
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
        raise MaukerjaMyFetchError(f"MauKerja refused {url}: {last_error}") from last_error

    def _fetch_xml(self, url: str) -> str:
        """Download one sitemap document, refusing an outsized body."""
        response = self._get(url, timeout=self._settings.sitemap_timeout_seconds)
        content = response.content
        if len(content) > self._settings.max_sitemap_bytes:
            raise MaukerjaMyResponseError(
                f"MauKerja sitemap {url} is {len(content)} bytes, over the "
                f"{self._settings.max_sitemap_bytes}-byte guard. The sitemap format "
                "or host changed; refusing to buffer it silently."
            )
        return content.decode(response.encoding or "utf-8", errors="replace")

    @staticmethod
    def _root_tag(xml: str) -> str:
        if not (xml or "").strip():
            raise MaukerjaMyResponseError("MauKerja sitemap is empty")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise MaukerjaMyResponseError(
                f"MauKerja sitemap is not well-formed XML: {exc}"
            ) from exc
        return root.tag.split("}")[-1]

    @staticmethod
    def parse_job_urlset(xml: str) -> list[tuple[str, str, str | None]]:
        """Parse a job ``<urlset>`` into ``(job_id, url, lastmod)`` tuples.

        Order is preserved (the board writes them newest-first). Entries whose
        URL is not a ``/job/<id>-<slug>`` ad are skipped.
        """
        if not (xml or "").strip():
            raise MaukerjaMyResponseError("MauKerja sitemap is empty")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise MaukerjaMyResponseError(
                f"MauKerja sitemap is not well-formed XML: {exc}"
            ) from exc
        root_tag = root.tag.split("}")[-1]
        if root_tag != "urlset":
            raise MaukerjaMyResponseError(
                f"MauKerja job sitemap root is <{root_tag}>, not <urlset>; "
                "the advertised format changed."
            )
        out: list[tuple[str, str, str | None]] = []
        for node in root.findall(f"{_SITEMAP_NS}url"):
            loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
            match = _JOB_ID.search(loc)
            if not match:
                if loc:
                    logger.warning("MauKerja sitemap URL is not an ad: {}", loc)
                continue
            lastmod = (node.findtext(f"{_SITEMAP_NS}lastmod") or "").strip() or None
            out.append((match.group(1), loc, lastmod))
        return out

    @staticmethod
    def child_job_sitemaps(xml: str) -> list[str]:
        """Child sitemap URLs of a ``<sitemapindex>`` whose name is a job sitemap."""
        if not (xml or "").strip():
            raise MaukerjaMyResponseError("MauKerja sitemap is empty")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise MaukerjaMyResponseError(
                f"MauKerja sitemap is not well-formed XML: {exc}"
            ) from exc
        root_tag = root.tag.split("}")[-1]
        if root_tag != "sitemapindex":
            raise MaukerjaMyResponseError(
                f"MauKerja sitemap root is <{root_tag}>, not <sitemapindex>"
            )
        children: list[str] = []
        for node in root.findall(f"{_SITEMAP_NS}sitemap"):
            loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
            if not loc:
                continue
            if _JOB_SITEMAP_NAME.match(urlparse(loc).path.rsplit("/", 1)[-1]):
                children.append(loc)
        return children

    def fetch_sitemap_entries(self) -> list[SitemapEntry]:
        """Walk the sitemap chain and return deduped, newest-first ad entries."""
        queue = [self._settings.sitemap_url]
        visited: set[str] = set()
        raw: list[tuple[str, str, str | None]] = []

        for _ in range(self._settings.max_sitemap_depth + 1):
            if not queue:
                break
            next_queue: list[str] = []
            for url in queue:
                if url in visited:
                    continue
                visited.add(url)
                xml = self._fetch_xml(url)
                tag = self._root_tag(xml)
                if tag == "urlset":
                    raw.extend(self.parse_job_urlset(xml))
                elif tag == "sitemapindex":
                    next_queue.extend(self.child_job_sitemaps(xml))
                else:
                    raise MaukerjaMyResponseError(
                        f"MauKerja sitemap {url} root is <{tag}>, not <urlset> or <sitemapindex>."
                    )
            queue = next_queue

        seen: set[str] = set()
        entries: list[SitemapEntry] = []
        for job_id, loc, lastmod in raw:
            if job_id in seen:
                continue
            seen.add(job_id)
            entries.append(
                SitemapEntry(job_id=job_id, url=loc, lastmod=lastmod, position=len(entries))
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
    ) -> tuple[list[RawMaukerjaMyJob], dict[str, str], int]:
        """Read the sitemap and fetch the selected ad pages.

        Returns ``(raw_jobs, failures, sitemap_entries)``. ``failures`` maps a
        failed URL to the reason; only successfully fetched pages become
        ``RawMaukerjaMyJob`` records because the sitemap holds no fallback
        fields.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}, 0

        entries = self.fetch_sitemap_entries()
        if not entries:
            raise MaukerjaMyResponseError(
                "MauKerja sitemap walked to zero /job/ entries. The board measured "
                "46,652 on 2026-11-20, so an empty result means the sitemap chain "
                "or its markup changed -- not that the board is empty."
            )

        selected = self.select_window(entries, budget)
        failures: dict[str, str] = {}
        records: list[RawMaukerjaMyJob] = []

        for entry in selected:
            if not self._settings.fetch_details:
                records.append(
                    RawMaukerjaMyJob(
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
            except MaukerjaMyFetchError as exc:
                failures[entry.url] = str(exc)
                logger.warning("MauKerja ad {} failed: {}", entry.job_id, exc)
                continue
            records.append(
                RawMaukerjaMyJob(
                    job_id=entry.job_id,
                    url=entry.url,
                    sitemap_position=entry.position,
                    sitemap_total=len(entries),
                    lastmod=entry.lastmod,
                    html_content=html,
                )
            )

        if not records and not failures:
            raise MaukerjaMyResponseError(
                "MauKerja discovery succeeded but no ad page was fetched -- "
                "raised rather than returned empty."
            )
        logger.info(
            "MauKerja: {} sitemap entr(ies), {} selected, {} fetched, {} failure(s)",
            len(entries),
            len(selected),
            len(records),
            len(failures),
        )
        return records, failures, len(entries)

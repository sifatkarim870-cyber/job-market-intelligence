"""Fetches raw postings from jobup.ch (Switzerland).

Discovery is jobup.ch's advertised sitemap index, measured 2026-11-20::

    /sitemaps/jobup/en/sitemap.xml        sitemapindex, 20 children
      -> .../job/sitemap.job-en.xml.gz    <urlset>, 30,590 job URLs, gzip

The walk follows only children under the ``/job/`` path, so the job sitemap is
found while the category, company, region and search sitemaps are skipped, and
a future paginated ``sitemap.job-en_N.xml.gz`` is picked up automatically.

The job sitemap is written **oldest-first** (top ``lastmod`` 2026-09-21, bottom
2026-11-20 on 2026-11-20). The client therefore sorts by ``lastmod`` descending
before applying the window, so ``fresh_rows`` really is the newest postings.

A capped run must still be useful in two directions:

  * the newest ``fresh_rows`` entries are **always** included;
  * the rest of the budget comes from a window that advances one budget-width
    per calendar day (``start_offset`` pins it), so the older tail is covered
    over successive runs instead of the same slice being re-read forever.

A failed ad page is not fatal and is not turned into a half-record: the sitemap
carries only the URL (no title or employer), so the failure is recorded and the
entry is skipped.
"""

from __future__ import annotations

import gzip
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from urllib.parse import urlparse

import requests
from loguru import logger

from .config import JobupChSettings
from .exceptions import JobupChFetchError, JobupChResponseError
from .models import RawJobupChJob, SitemapEntry

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
#: Job ad detail ids are UUIDs embedded in ``/en/jobs/detail/<uuid>/``.
_JOB_ID = re.compile(r"/jobs/detail/([0-9a-fA-F-]{36})")
#: Only children under the ``/job/`` path are job-ad sets.
_JOB_PATH_MARKER = "/job/"
_GZIP_MAGIC = b"\x1f\x8b"


class JobupChClient:
    """Walks the sitemap chain and fetches the ad pages it points at."""

    def __init__(self, settings: JobupChSettings | None = None) -> None:
        self._settings = settings or JobupChSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-CH,en;q=0.9,fr-CH;q=0.8,de-CH;q=0.7",
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
        """GET with bounded exponential backoff; raises ``JobupChFetchError``."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=timeout)
                if response.status_code in (404, 410):
                    raise JobupChFetchError(f"HTTP {response.status_code} for {url}")
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "jobup.ch request {}/{} failed for {}: {}",
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
        raise JobupChFetchError(f"jobup.ch refused {url}: {last_error}") from last_error

    def _fetch_xml(self, url: str) -> str:
        """Download one sitemap document (gunzipping it if needed)."""
        response = self._get(url, timeout=self._settings.sitemap_timeout_seconds)
        content = response.content
        if len(content) > self._settings.max_sitemap_bytes:
            raise JobupChResponseError(
                f"jobup.ch sitemap {url} is {len(content)} bytes, over the "
                f"{self._settings.max_sitemap_bytes}-byte guard. The sitemap format "
                "or host changed; refusing to buffer it silently."
            )
        if content[:2] == _GZIP_MAGIC:
            try:
                content = gzip.decompress(content)
            except OSError as exc:
                raise JobupChResponseError(
                    f"jobup.ch sitemap {url} is gzip but does not decompress: {exc}"
                ) from exc
            if len(content) > self._settings.max_sitemap_bytes:
                raise JobupChResponseError(
                    f"jobup.ch sitemap {url} inflates to {len(content)} bytes, over the "
                    f"{self._settings.max_sitemap_bytes}-byte guard."
                )
        charset = response.encoding or "utf-8"
        return content.decode(charset, errors="replace")

    @staticmethod
    def _root_tag(xml: str) -> tuple[str, ET.Element]:
        if not (xml or "").strip():
            raise JobupChResponseError("jobup.ch sitemap is empty")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise JobupChResponseError(f"jobup.ch sitemap is not well-formed XML: {exc}") from exc
        return root.tag.split("}")[-1], root

    @staticmethod
    def parse_job_urlset(xml: str) -> list[tuple[str, str, str | None]]:
        """Parse a job ``<urlset>`` into ``(job_id, url, lastmod)`` tuples.

        Order is preserved as written (oldest first); the caller sorts by
        ``lastmod``. Entries whose URL is not a ``/jobs/detail/<uuid>`` ad are
        skipped.
        """
        root_tag, root = JobupChClient._root_tag(xml)
        if root_tag != "urlset":
            raise JobupChResponseError(
                f"jobup.ch job sitemap root is <{root_tag}>, not <urlset>; "
                "the advertised format changed."
            )
        out: list[tuple[str, str, str | None]] = []
        for node in root.findall(f"{_SITEMAP_NS}url"):
            loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
            match = _JOB_ID.search(loc)
            if not match:
                if loc:
                    logger.warning("jobup.ch sitemap URL is not an ad: {}", loc)
                continue
            lastmod = (node.findtext(f"{_SITEMAP_NS}lastmod") or "").strip() or None
            out.append((match.group(1).lower(), loc, lastmod))
        return out

    @staticmethod
    def child_job_sitemaps(xml: str) -> list[str]:
        """Child sitemap URLs of a ``<sitemapindex>`` under the ``/job/`` path."""
        root_tag, root = JobupChClient._root_tag(xml)
        if root_tag != "sitemapindex":
            raise JobupChResponseError(f"jobup.ch sitemap root is <{root_tag}>, not <sitemapindex>")
        children: list[str] = []
        for node in root.findall(f"{_SITEMAP_NS}sitemap"):
            loc = (node.findtext(f"{_SITEMAP_NS}loc") or "").strip()
            if loc and _JOB_PATH_MARKER in urlparse(loc).path:
                children.append(loc)
        return children

    @staticmethod
    def _lastmod_sort_key(lastmod: str | None) -> datetime:
        """Sort key for ``lastmod``; missing or unparseable sorts oldest."""
        if not lastmod:
            return datetime.min
        text = lastmod.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return datetime.min
        return parsed.replace(tzinfo=None)

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
                tag, _root = self._root_tag(xml)
                if tag == "urlset":
                    raw.extend(self.parse_job_urlset(xml))
                elif tag == "sitemapindex":
                    next_queue.extend(self.child_job_sitemaps(xml))
                else:
                    raise JobupChResponseError(
                        f"jobup.ch sitemap {url} root is <{tag}>, not <urlset> or <sitemapindex>."
                    )
            queue = next_queue

        seen: set[str] = set()
        deduped: list[tuple[str, str, str | None]] = []
        for job_id, loc, lastmod in raw:
            if job_id in seen:
                continue
            seen.add(job_id)
            deduped.append((job_id, loc, lastmod))

        # The sitemap is oldest-first; sort newest-first so ``fresh_rows`` is true.
        deduped.sort(key=lambda item: self._lastmod_sort_key(item[2]), reverse=True)
        return [
            SitemapEntry(job_id=job_id, url=loc, lastmod=lastmod, position=index)
            for index, (job_id, loc, lastmod) in enumerate(deduped)
        ]

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
    ) -> tuple[list[RawJobupChJob], dict[str, str], int]:
        """Read the sitemap and fetch the selected ad pages.

        Returns ``(raw_jobs, failures, sitemap_entries)``. ``failures`` maps a
        failed URL to the reason; only successfully fetched pages become
        ``RawJobupChJob`` records because the sitemap holds no fallback fields.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}, 0

        entries = self.fetch_sitemap_entries()
        if not entries:
            raise JobupChResponseError(
                "jobup.ch sitemap walked to zero job entries. The board measured "
                "30,590 on 2026-11-20, so an empty result means the sitemap chain "
                "or its markup changed -- not that the board is empty."
            )

        selected = self.select_window(entries, budget)
        failures: dict[str, str] = {}
        records: list[RawJobupChJob] = []

        for entry in selected:
            if not self._settings.fetch_details:
                records.append(
                    RawJobupChJob(
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
            except JobupChFetchError as exc:
                failures[entry.url] = str(exc)
                logger.warning("jobup.ch ad {} failed: {}", entry.job_id, exc)
                continue
            records.append(
                RawJobupChJob(
                    job_id=entry.job_id,
                    url=entry.url,
                    sitemap_position=entry.position,
                    sitemap_total=len(entries),
                    lastmod=entry.lastmod,
                    html_content=html,
                )
            )

        if not records and not failures:
            raise JobupChResponseError(
                "jobup.ch discovery succeeded but no ad page was fetched -- "
                "raised rather than returned empty."
            )
        logger.info(
            "jobup.ch: {} sitemap entr(ies), {} selected, {} fetched, {} failure(s)",
            len(entries),
            len(selected),
            len(records),
            len(failures),
        )
        return records, failures, len(entries)

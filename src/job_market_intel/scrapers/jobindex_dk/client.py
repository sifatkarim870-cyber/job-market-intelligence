"""HTTP client for discovering and fetching Jobindex ads.

Discovery never walks ``?page=``: robots.txt disallows it. It reads the board's
own ``/sitemap/area.gz`` (759 ``/jobsoegning/<area>`` pages) and samples a
rotating window of those listing pages, plus the newest-first ``/jobsoegning``
page. Every listing page embeds the same ``var Stash`` JSON object, whose
``searchResponse.results`` array is the ad list; ads are deduped by ``tid``.

Content is one request per ad. When the listing snippet exposes the canonical
``/jobannonce/<tid>/<slug>`` URL it is fetched directly (full body). Otherwise
``/vis-job/<tid>`` is fetched and its ``<link rel="canonical">`` is followed if
it points at a ``/jobannonce/`` page; a teaser-only employer ad canonicalises
to itself, so the teaser text is used and the ad is flagged as such. The
robots-disallowed ``/c?...`` redirect link is never fetched.

A capped run must not re-read only the first area page forever, so the window
it fetches is not simply "the first N rows": the newest ``fresh_rows`` rows are
always included, and the rest of the budget comes from a window that advances
one window-width per calendar day (``start_offset`` pins it).
"""

from __future__ import annotations

import gzip
import json
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from loguru import logger

from .config import JobIndexSettings
from .exceptions import JobIndexFetchError, JobIndexParseError, JobIndexResponseError
from .models import RawJobIndexJob

#: A canonical ad link, with the ``\\/`` escaping the site uses in inline JSON
#: already normalised by the caller. The id prefix is one optional letter
#: (``h1716213`` human ad, ``r14107185`` robot/feed ad), then at least four
#: digits, which rejects prose anchors such as ``/jobannonce/reportage``.
_JOBANNONCE_RE = re.compile(r"jobannonce/([A-Za-z]?\d{4,})/([A-Za-z0-9_\-]+)")
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_STASH_MARKER = "var Stash = {"
_CANONICAL_RE = re.compile(
    r"<link[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']([^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
_CANONICAL_REVERSED_RE = re.compile(
    r"<link[^>]*href=[\"']([^\"']+)[\"'][^>]*rel=[\"']canonical[\"'][^>]*>",
    re.IGNORECASE,
)


def _escape_free(text: str) -> str:
    """Undo the JSON ``\\/`` escaping used inside the listing snippet."""
    return text.replace("\\/", "/")


def jobannonce_path(snippet: str, job_id: str) -> str | None:
    """Return ``/jobannonce/<tid>/<slug>`` if the snippet links this ad.

    The snippet embeds the ad's own link with escaped slashes. A different id
    found in the same snippet is ignored: several layout links can coexist, and
    following one would fetch another ad under this ad's metadata.
    """
    match = _JOBANNONCE_RE.search(_escape_free(snippet or ""))
    if not match or match.group(1) != job_id:
        return None
    return f"/jobannonce/{match.group(1)}/{match.group(2)}"


def extract_stash(html: str) -> dict[str, Any]:  # noqa: C901 - brace matcher
    """Parse the ``var Stash = {...}`` JSON object embedded in a listing page.

    The object is ~270 KB on the live page and is not on a single line, so it
    is located by marker and brace-matched rather than matched with a regex.
    """
    marker_at = html.find(_STASH_MARKER)
    if marker_at < 0:
        raise JobIndexParseError("listing page has no 'var Stash' object")
    start = html.find("{", marker_at)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(html[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise JobIndexParseError(f"unparseable 'var Stash' object: {exc}") from exc
                if not isinstance(payload, dict):
                    raise JobIndexParseError("'var Stash' object is not a JSON object")
                return payload
    raise JobIndexParseError("unterminated 'var Stash' object")


def listing_results(html: str) -> list[dict[str, Any]]:
    """Return ``searchResponse.results`` from one listing page.

    The store key is discovered structurally (the one top-level entry with a
    ``storeData`` dict) because the page path in the key is an implementation
    detail that may move.
    """
    payload = extract_stash(html)
    store: dict[str, Any] | None = None
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("storeData"), dict):
            store = value["storeData"]
            break
    if store is None:
        raise JobIndexParseError("'var Stash' has no storeData entry")
    response = store.get("searchResponse")
    if not isinstance(response, dict):
        raise JobIndexParseError("'var Stash' storeData has no searchResponse object")
    results = response.get("results")
    if not isinstance(results, list):
        raise JobIndexParseError("searchResponse.results is not a list")
    return [row for row in results if isinstance(row, dict) and row.get("tid")]


def canonical_url(html: str) -> str | None:
    """The page's ``<link rel="canonical">`` target, in either attribute order."""
    for pattern in (_CANONICAL_RE, _CANONICAL_REVERSED_RE):
        match = pattern.search(html)
        if match:
            return match.group(1).strip()
    return None


def _tid_number(job_id: str) -> int:
    digits = re.sub(r"\D", "", job_id)
    return int(digits) if digits else 0


class JobIndexClient:
    """Client for jobindex.dk, Denmark's largest commercial job board."""

    def __init__(self, settings: JobIndexSettings | None = None) -> None:
        self._settings = settings or JobIndexSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
                "Referer": self._settings.base_url + "/",
            }
        )
        self._last_request_at: float | None = None

    # ------------------------------------------------------------------ HTTP

    def _throttle(self) -> None:
        """Keep a polite gap between any two requests."""
        if self._last_request_at is None or self._settings.rate_limit_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.rate_limit_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(self, url: str) -> requests.Response:
        """GET with bounded backoff and a robots-aware delay between requests."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds

        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=self._settings.request_timeout)
                if response.status_code in (404, 410):
                    raise JobIndexFetchError(f"HTTP {response.status_code} fetching {url}")
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "jobindex.dk request {}/{} failed for {}: {}",
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

        raise JobIndexFetchError(f"jobindex.dk refused {url}: {last_error}") from last_error

    def _fetch_html(self, url: str) -> str:
        return self._request(url).text

    # ------------------------------------------------------------- discovery

    def area_urls(self) -> list[str]:
        """Area listing URLs from the advertised ``area.gz`` sitemap."""
        response = self._request(self._settings.sitemap_url)
        raw = response.content
        if raw[:2] == b"\x1f\x8b":
            try:
                text = gzip.decompress(raw).decode("utf-8", errors="replace")
            except OSError as exc:
                raise JobIndexParseError(f"area sitemap is not readable gzip: {exc}") from exc
        else:
            text = raw.decode("utf-8", errors="replace")

        if "<sitemapindex" in text:
            raise JobIndexParseError(
                "area.gz is a <sitemapindex>, not the expected <urlset> of area pages"
            )
        areas = [
            loc
            for loc in (_match.strip() for _match in _LOC_RE.findall(text))
            if "/jobsoegning/" in loc
        ]
        # Stable order: the sitemap is regenerated often and its order is not a
        # contract, so a deterministic sort is what makes the rotating window
        # cover every area exactly once per cycle.
        areas = sorted(dict.fromkeys(areas))
        if not areas:
            raise JobIndexResponseError(
                f"no area pages in {self._settings.sitemap_url}; the sitemap shape changed"
            )
        return areas

    def discover(self) -> tuple[list[dict[str, Any]], int]:  # noqa: C901 - branch per failure
        """Return ``(rows, pages_scraped)``, deduped by ``tid``, newest first."""
        rows: dict[str, dict[str, Any]] = {}
        pages_scraped = 0

        try:
            main_html = self._fetch_html(self._settings.listing_url)
        except JobIndexFetchError as exc:
            logger.warning("jobindex.dk newest-first listing failed: {}", exc)
        else:
            pages_scraped += 1
            try:
                main_rows = listing_results(main_html)
            except JobIndexParseError as exc:
                logger.warning("jobindex.dk newest-first page unparseable: {}", exc)
            else:
                for row in main_rows:
                    rows.setdefault(str(row["tid"]), row)
                logger.info(
                    "jobindex.dk newest-first page: {} row(s) ({} unique so far)",
                    len(main_rows),
                    len(rows),
                )

        areas = self.area_urls()
        page_budget = min(self._settings.max_area_pages, len(areas))
        start = self.rotation_offset(len(areas), page_budget)
        window = areas[start:] + areas[:start]

        for area_url in window[:page_budget]:
            try:
                html = self._fetch_html(area_url)
            except JobIndexFetchError as exc:
                logger.warning("jobindex.dk area page {} failed: {}", area_url, exc)
                continue
            pages_scraped += 1
            try:
                area_rows = listing_results(html)
            except JobIndexParseError as exc:
                logger.warning("jobindex.dk area page {} unparseable: {}", area_url, exc)
                continue
            new = 0
            for row in area_rows:
                job_id = str(row["tid"])
                if job_id not in rows:
                    rows[job_id] = row
                    new += 1
            logger.info(
                "jobindex.dk area page {}: {} row(s), {} new ({} unique)",
                area_url.rsplit("/", 1)[-1],
                len(area_rows),
                new,
                len(rows),
            )

        if not rows:
            raise JobIndexResponseError(
                f"no ads found on the newest-first page or in {page_budget} area "
                f"page(s) of {self._settings.sitemap_url}. An empty result means the "
                "markup changed -- not that the board is empty -- so it is raised "
                "rather than returned empty."
            )

        ordered = sorted(rows.values(), key=self._sort_key, reverse=True)
        logger.info(
            "jobindex.dk discovered {} unique ad(s) across {} page(s).",
            len(ordered),
            pages_scraped,
        )
        return ordered, pages_scraped

    @staticmethod
    def _sort_key(row: dict[str, Any]) -> tuple[str, int]:
        """Newest ``firstdate`` first, then the higher (newer) ad id."""
        return (str(row.get("firstdate") or ""), _tid_number(str(row.get("tid") or "")))

    # --------------------------------------------------------------- windows

    def rotation_offset(self, window_size: int, step: int) -> int:
        """Where the rotating area window starts.

        ``start_offset`` pins it. Otherwise it advances one window-width per
        calendar day, so consecutive daily runs tile the sitemap instead of
        overlapping it.
        """
        if window_size <= 0:
            return 0
        if self._settings.start_offset is not None:
            return self._settings.start_offset % window_size
        return (date.today().toordinal() * max(1, step)) % window_size

    def select_window(self, items: list[Any], budget: int) -> list[Any]:
        """The newest ``fresh_rows`` items plus a rotating slice of the rest."""
        if budget >= len(items):
            return list(items)

        fresh_n = min(self._settings.fresh_rows, budget, len(items))
        chosen = list(items[:fresh_n])
        tail = list(items[fresh_n:])
        tail_budget = budget - len(chosen)
        if tail and tail_budget > 0:
            start = self.rotation_offset(len(tail), tail_budget)
            rotated = tail[start:] + tail[:start]
            chosen.extend(rotated[:tail_budget])
        return chosen[:budget]

    # ----------------------------------------------------------------- fetch

    def fetch_job(self, listing: dict[str, Any]) -> RawJobIndexJob:
        """Fetch the fullest page this ad publishes on jobindex.dk."""
        job_id = str(listing["tid"])
        path = jobannonce_path(str(listing.get("html") or ""), job_id)
        if path is not None:
            url = urljoin(self._settings.base_url, path)
            return RawJobIndexJob(
                job_id=job_id,
                listing=listing,
                ad_url=url,
                html_content=self._fetch_html(url),
                page_kind="jobannonce",
            )

        vis_url = urljoin(self._settings.base_url, f"/vis-job/{job_id}")
        html = self._fetch_html(vis_url)
        canonical = canonical_url(html)
        if canonical and f"/jobannonce/{job_id}/" in canonical:
            full_url = urljoin(self._settings.base_url, canonical)
            try:
                full_html = self._fetch_html(full_url)
            except JobIndexFetchError as exc:
                logger.warning(
                    "jobindex.dk canonical ad page {} failed after teaser {}: {}",
                    full_url,
                    vis_url,
                    exc,
                )
            else:
                return RawJobIndexJob(
                    job_id=job_id,
                    listing=listing,
                    ad_url=full_url,
                    html_content=full_html,
                    page_kind="jobannonce",
                )
        return RawJobIndexJob(
            job_id=job_id,
            listing=listing,
            ad_url=vis_url,
            html_content=html,
            page_kind="vis_job",
        )

    def fetch_raw_jobs(
        self, max_jobs: int | None = None
    ) -> tuple[list[RawJobIndexJob], list[str], int, int]:
        """Discover the board and fetch the window this run should persist.

        Returns ``(raw_jobs, failed_urls, pages_scraped, discovered_count)``.
        """
        discovered, pages_scraped = self.discover()
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        selected = self.select_window(discovered, budget)
        logger.info(
            "jobindex.dk selected {} of {} discovered ad(s) for detail retrieval (budget={}).",
            len(selected),
            len(discovered),
            budget,
        )

        raw_jobs: list[RawJobIndexJob] = []
        failed_urls: list[str] = []
        for listing in selected:
            try:
                raw_jobs.append(self.fetch_job(listing))
            except JobIndexFetchError as exc:
                job_id = str(listing.get("tid"))
                logger.warning("Failed to fetch jobindex.dk ad id={}: {}", job_id, exc)
                failed_urls.append(f"{job_id}: {exc}")

        logger.info(
            "Fetched {} of {} selected jobindex.dk ad page(s) ({} failure(s)).",
            len(raw_jobs),
            len(selected),
            len(failed_urls),
        )
        return raw_jobs, failed_urls, pages_scraped, len(discovered)

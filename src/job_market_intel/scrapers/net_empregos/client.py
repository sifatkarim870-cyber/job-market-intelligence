"""Fetches raw postings from Net-Empregos, a Portuguese job board.

Two steps:

  1. **Discovery.** Walk ``/jobs?page=N``, collecting ``/<id>/<slug>/``
     anchors. Measured 2026-10-16: exactly **18** postings per page, 18 new on
     every page, so the pager is real. The id is 6-12 digits. The listing
     writes the same posting three times (logo, title, "Ver Oferta") with a
     mix of quoted and unquoted ``href`` values, so discovery parses anchors
     with BeautifulSoup and deduplicates by id rather than matching one
     quoting style with a regex.

  2. **Detail.** Fetch each link and read the schema.org ``JobPosting`` in its
     JSON-LD block. The JSON is malformed (raw newlines in the description), so
     the parser uses ``json.loads(block, strict=False)``.

robots.txt returns **HTTP 406 as text/html** -- not a real robots file, so
under RFC 9309 there is no restriction to parse. ``/jobs`` and
``/jobs/<id>/<slug>/`` are both fetchable.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import NetEmpregosSettings
from .exceptions import NetEmpregosFetchError, NetEmpregosResponseError

#: ``/<numeric id>/<slug>/``. The id is 6-12 digits and the slug is at
#: least four characters. Measured 2026-10-29: every card links to the same
#: posting three times (logo, title, "Ver Oferta"), so anchors must be
#: deduplicated by id.
_DETAIL_PATH = re.compile(r"^/(\d{6,12})/[^/?#]{4,}/?$")


def extract_detail_paths(html: str) -> dict[str, str]:
    """Return ``{job_id: path}`` for every posting linked on a listing page.

    Parses anchors instead of scanning raw HTML for one exact quoting style.
    The listing mixes quoted and unquoted attributes on the same page
    (``href="/16181991/..."`` for the logo and ``href=/16181991/...`` for the
    card text), and the 2026-10-17 CI run observed HTTP 200 with zero matches
    on this exact regex -- a template variant that emits unquoted or absolute
    links silently costs the whole run. ``BeautifulSoup`` normalises quoting,
    entity escaping and absolute URLs, so all three shapes reduce to the same
    path.
    """
    found: dict[str, str] = {}
    for anchor in BeautifulSoup(html or "", "html.parser").find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        parsed = urlparse(href)
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            continue
        match = _DETAIL_PATH.match(parsed.path)
        if match is None:
            continue
        found.setdefault(match.group(1), parsed.path)
    return found


class NetEmpregosClient:
    """Fetches postings from Net-Empregos's server-rendered listing and detail pages."""

    def __init__(self, settings: NetEmpregosSettings | None = None) -> None:
        self._settings = settings or NetEmpregosSettings()

    # ------------------------------------------------------------------ fetch

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
            raise NetEmpregosFetchError(
                f"Net-Empregos unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise NetEmpregosFetchError(f"Net-Empregos refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page. Page 1 omits the query entirely."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{job_id: detail_path}`` for one page of the listing."""
        html = self._fetch(self.listing_url(page))
        found = extract_detail_paths(html)
        logger.info("net-empregos listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    # ------------------------------------------------------------- discovery

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk the listing, collecting detail paths.

        Returns ``({job_id: {"path": ..., "page": ...}}, failures)``.
        """
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except NetEmpregosFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("net-empregos listing page {} failed: {}", page, exc)
                break

            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue

            new = 0
            for job_id, path in links.items():
                if job_id not in found:
                    found[job_id] = {"path": path, "page": page}
                    new += 1

            # Collect first, stop second: a short final page still holds real
            # postings, and discarding it loses the tail of every run.
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "net-empregos page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise NetEmpregosResponseError(
                f"no postings found in {self._settings.max_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result here means the "
                "listing markup changed -- not that the board is empty -- so it "
                "is raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures.

        Failures are collected rather than raised: one posting or one listing
        page failing must not cost a run.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for job_id, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except NetEmpregosFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("net-empregos job page {} failed: {}", job_id, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": job_id,
                    "html": html,
                    "url": url,
                    "listing_page": meta["page"],
                }
            )

        if not records and not failures:
            raise NetEmpregosResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("net-empregos: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

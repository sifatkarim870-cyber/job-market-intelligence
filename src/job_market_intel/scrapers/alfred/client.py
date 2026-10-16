"""Fetches raw postings from Alfred, the Icelandic job board.

Discovery reads the **sitemap**, not the homepage
------------------------------------------------
Alfred's homepage embeds a complete-looking job feed in ``__NEXT_DATA__`` --
``props.pageProps.jobs`` with ``totalCount: 572`` and ``totalPages: 22`` -- and
that is the wrong thing to scrape, for three measured reasons:

* it serves only **27** records per response;
* every pagination attempt returns a **byte-identical** 667,028-byte page with
  **0 new** ids -- ``/?page=2``, ``/?p=2`` and ``/?page=3`` are all page 1,
  because the page is statically generated;
* ``/starf?page=2`` and ``/page/2`` are HTTP 404.

robots.txt disallows ``/api/*`` and every filter parameter (``*jobtypes=*``,
``*tags=*``, ``*zips=*``, ``*cat=*``), so the JSON API and the faceted views are
unavailable by the site's own rules -- and the API is the one path that would
otherwise have made the whole feed reachable in a few requests.

What robots *does* nominate is ``Sitemap: https://alfred.is/sitemap.xml``, an
index whose ``sitemap-jobs.xml`` child holds **624** ``/starf/`` URLs. So
discovery reads the sitemap: it is both the compliant route and the only one
that reaches the whole board.

Detail pages then carry a schema.org ``JobPosting`` at the top level, and the
payload names the posting in no way at all -- no ``identifier`` -- so the URL
slug is the key.
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

from .config import AlfredSettings
from .exceptions import AlfredFetchError, AlfredResponseError

#: The last path segment of a posting URL, e.g. "adstod-a-tannlknastofu".
#: Anchored, minimum five characters, and neither end may be a hyphen: a real
#: slug never has one, and accepting it would let a malformed sitemap entry
#: through as a key. The two alternatives are there because a short slug has no
#: interior at all -- "3d-artist" is only four characters of body.
_SLUG = re.compile(r"^(?:[a-z0-9]{5,}|[a-z0-9][a-z0-9-]{3,197}[a-z0-9])$")


class AlfredClient:
    """Fetches postings from Alfred's sitemap and server-rendered detail pages."""

    def __init__(self, settings: AlfredSettings | None = None) -> None:
        self._settings = settings or AlfredSettings()

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
            raise AlfredFetchError(
                f"Alfred unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise AlfredFetchError(f"Alfred refused {url}: {exc}") from exc

    # ------------------------------------------------------------- discovery

    def _sitemap_urls(self, xml: str) -> list[str]:
        """All <loc> values in a sitemap index or urlset document."""
        soup = BeautifulSoup(xml, "xml")
        return [u.get_text(strip=True) for u in soup.find_all("loc")]

    def _resolve_jobs_sitemap(self, index_xml: str, failures: dict[str, str]) -> tuple[str, str]:
        """Return ``(xml, url)`` for the sitemap that holds the postings.

        robots names ``sitemap.xml``, normally an index whose
        ``sitemap-jobs.xml`` child holds the ``/starf/`` URLs and whose
        ``sitemap-web.xml`` sibling holds five non-job URLs. If the named child
        is missing, the index is treated as a flat urlset rather than returning
        nothing: an index silently replaced by a urlset would otherwise look
        exactly like a board with no vacancies.
        """
        children = self._sitemap_urls(index_xml)
        logger.info("alfred sitemap index: {} child(ren)", len(children))

        for child in children:
            if self._settings.jobs_sitemap_name in child:
                try:
                    return self._fetch(child), child
                except AlfredFetchError as exc:
                    failures[child] = str(exc)
                    logger.warning("alfred jobs sitemap failed: {}", exc)
                    time.sleep(self._settings.inter_request_delay_seconds)
                    break

        logger.info("alfred: no named jobs child found; treating the index as a urlset")
        return index_xml, self._settings.sitemap_url

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Read the sitemap index, then its jobs child, collecting posting URLs.

        Returns ``({slug: {"url": ...}}, failures)``.
        """
        failures: dict[str, str] = {}
        found: dict[str, dict] = {}

        try:
            index = self._fetch(self._settings.sitemap_url)
        except AlfredFetchError as exc:
            failures[self._settings.sitemap_url] = str(exc)
            raise AlfredResponseError(
                f"could not read the sitemap index at {self._settings.sitemap_url}: {exc}. "
                "That URL is the only complete discovery route this board offers, so "
                "a failure here is raised rather than returning an empty batch."
            ) from exc

        jobs_xml, jobs_url = self._resolve_jobs_sitemap(index, failures)

        for loc in self._sitemap_urls(jobs_xml):
            path = urlparse(loc).path
            if self._settings.detail_path_prefix not in path:
                continue
            slug = path.rstrip("/").rsplit("/", 1)[-1]
            if not _SLUG.match(slug):
                continue
            found.setdefault(slug, {"url": loc, "sitemap": jobs_url})
            if len(found) >= self._settings.max_jobs_per_run:
                logger.info("alfred: job budget reached during discovery")
                break

        logger.info("alfred: discovered {} posting URL(s) from {}", len(found), jobs_url or "?")
        if not found and not failures:
            raise AlfredResponseError(
                f"no posting URLs under {self._settings.detail_path_prefix!r} in the "
                "sitemap. An empty result here means the sitemap structure "
                "changed -- not that the board is empty -- so it is raised "
                "rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover then fetch postings, returning raw records and failures.

        Failures are collected rather than raised: one posting failing must not
        cost a run.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for slug, meta in discovered.items():
            if len(records) >= budget:
                break
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(meta["url"])
                except AlfredFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("alfred job page {} failed: {}", slug, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append({"slug": slug, "html": html, "url": meta["url"]})

        if not records and not failures:
            raise AlfredResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("alfred: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

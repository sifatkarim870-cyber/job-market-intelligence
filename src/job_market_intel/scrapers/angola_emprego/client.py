"""Fetches raw postings from Angola Emprego, an Angolan job board.

Two steps:

  1. **Discovery.** Walk ``/vagas?page=N``, collecting ``/vagas/<slug>`` links.
     Measured 2026-10-18: exactly **15** per page, and the pager is real --
     ``?page=2`` returned **15 new** paths.

  2. **Detail.** Fetch each link and read the schema.org ``JobPosting`` in its
     JSON-LD block. Blocks are malformed on some pages, so the parser tries a
     strict ``json.loads`` and falls back to ``strict=False``.

robots.txt is real ``text/plain`` (460 bytes) with ``User-agent: *`` ->
``Allow: /``. It disallows ``/login``, ``/register``, ``/perfil``, ``/planos``,
``/pagamento``, ``/vagas-sugeridas``, ``/linkstorage``, ``/auth/`` and three
**query-parameter searches on the listing path**::

    Disallow: /vagas?q=
    Disallow: /vagas?location=
    Disallow: /vagas?category=
    Disallow: /?s=

Those are the site's own duplicate-content rules. Discovery therefore walks
``?page=N`` and never filters by query -- ``?page=`` is not among the
disallowed parameters, so the pager is compliant.
"""

from __future__ import annotations

import re
import time

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import AngolaEmpregoSettings
from .exceptions import AngolaEmpregoFetchError, AngolaEmpregoResponseError

#: ``/vagas/<slug>``. Slugs are hyphenated words, optionally ending in a
#: numeric id (``...-4818``), so the shape is required rather than guessed.
#:
#: The host prefix is **optional** on purpose. Measured 2026-10-18: every one of
#: the 15 listing hrefs is **absolute** -- ``href="https://angolaemprego.com/
#: vagas/<slug>"`` -- and *zero* are relative. A pattern anchored on
#: ``href="/vagas/..."`` therefore matched nothing at all on a board serving 15
#: postings a page, which is what CI run 39032134903 did. The first version of
#: this scraper had exactly that bug and the local probe did not catch it,
#: because the probe resolved links with ``urljoin``, which normalizes both
#: forms and so disagreed with the implementation about what the site emits.
_JOB_LINK = re.compile(r'href="(?:https?://[^"/]+)?(/vagas/[^"?#]{8,160}/?)"')
#: The bare ``/vagas/`` listing itself, which must not be treated as a posting.
_LISTING_ONLY = "/vagas/"


class AngolaEmpregoClient:
    """Fetches postings from Angola Emprego's server-rendered pages."""

    def __init__(self, settings: AngolaEmpregoSettings | None = None) -> None:
        self._settings = settings or AngolaEmpregoSettings()

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
            raise AngolaEmpregoFetchError(
                f"Angola Emprego unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise AngolaEmpregoFetchError(f"Angola Emprego refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        """URL for one listing page. Page 1 omits the query entirely."""
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        """Return ``{slug: detail_path}`` for one page of the listing."""
        html = self._fetch(self.listing_url(page))
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            path = m.group(1)
            if path.rstrip("/") == _LISTING_ONLY.rstrip("/"):
                continue
            found.setdefault(path.strip("/").split("/")[-1], path)
        logger.info("angola_emprego listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    # ------------------------------------------------------------- discovery

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk the listing, collecting detail paths.

        Returns ``({slug: {"path": ..., "page": ...}}, failures)``.
        """
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except AngolaEmpregoFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("angola_emprego listing page {} failed: {}", page, exc)
                break

            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue

            new = 0
            for slug, path in links.items():
                if slug not in found:
                    found[slug] = {"path": path, "page": page}
                    new += 1

            # Collect first, stop second: a short final page still holds real
            # postings, and discarding it loses the tail of every run.
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "angola_emprego page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise AngolaEmpregoResponseError(
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
        for slug, meta in discovered.items():
            if len(records) >= budget:
                break
            url = f"{self._settings.base_url}{meta['path']}"
            html = None
            if self._settings.fetch_description:
                try:
                    html = self._fetch(url)
                except AngolaEmpregoFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("angola_emprego job page {} failed: {}", slug, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append({"job_id": slug, "html": html, "url": url, "listing_page": meta["page"]})

        if not records and not failures:
            raise AngolaEmpregoResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returning empty."
            )
        logger.info("angola_emprego: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

"""Fetches raw job data from Jobinja.

This module's only responsibility: discover job URLs by paginating the
server-rendered listing, fetch each job's detail page, and hand back raw
``{"url", "html"}`` dictionaries. Parsing/validation of a page's content
is ``parser.py``'s job — same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-10-07)
---------------------------------------------------
Jobinja has no public JSON API (the ``/api/v10/*`` routes found in
``end_user.bundle.js`` are auth-only resume/notification endpoints —
``/api/v10/jobs`` etc. all 404 with a structured
``{"message": "messages.api_not_found"}``) and no sitemaps
(``/sitemap.xml`` → 404), so this client uses the two things the site
*does* serve in the open:

* **Discovery — ``/jobs?page=N``.** The listing is server-rendered with
  20 detail links per page, strictly newest-first (page 1 sampled
  datePosted 2026-10-06, page 421 2026-08-27, page 842 2026-08-08,
  page 843 empty → ≈16.8k-job corpus), zero overlap between pages, and
  a working ``rel="next"`` chain (``/jobs?page=2``). Because ordering
  is trustworthy, ``start_page`` alone steers a run: CI reads from 1
  (the newest window), a chunked backfill from a raised page number.
  Cards append ``?_ref=…&_t=…`` tracking params — stripped here so the
  same job always yields the same URL.
* **Detail — the job page itself** (``/companies/{co}/jobs/{code}/
  {slug}``). Each page server-renders its full record as schema.org
  JSON-LD ``JobPosting`` (6/6 sampled) plus ``<h4>…</h4><div
  class="tags">`` metadata sections — see ``models.py`` for the field
  inventory. One dead/delisted link costs that page, not the run: a
  per-job fetch failure is logged and skipped, while a *listing* page
  failure stays fatal (discovery itself is broken then).

No auth, no cookies, no signing — plain GETs with a browser-style
User-Agent. ``common/http_client.py`` is GET-only with no listing/page
parsing, so this client does its own request loop while reusing the
shared error taxonomy (``TransientHTTPError``/``PermanentHTTPError``)
and ``call_with_retry``.
"""

from __future__ import annotations

import re
import time

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import JobinjaSettings
from .exceptions import JobinjaFetchError, JobinjaResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Detail links in the listing HTML: absolute ``/companies/{co}/jobs/…``
#: hrefs (company pages also link ``/companies/{co}/jobs`` — no ``/jobs/
#: {code}`` segment beyond it — so this shape is job-only).
_JOB_URL_RE = re.compile(r'href="(https://jobinja\.ir/companies/[^"]+/jobs/[^"]+)"')


class JobinjaClient:
    """Fetches the current Jobinja job pages via listing pagination."""

    def __init__(self, settings: JobinjaSettings | None = None) -> None:
        self._settings = settings or JobinjaSettings()
        # One keep-alive session: a full backfill (~17k pages) would pay
        # a fresh TCP+TLS handshake each without it.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _request_text(self, url: str, *, what: str) -> str:
        """GET one URL with retries; return the response body as text."""
        settings = self._settings

        def _do() -> str:
            try:
                response = self._session.get(url, timeout=settings.request_timeout_seconds)
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientHTTPError(str(exc)) from exc
            except requests.RequestException as exc:
                raise PermanentHTTPError(str(exc)) from exc

            if response.status_code in _RETRYABLE_STATUS:
                raise TransientHTTPError(f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise PermanentHTTPError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            return response.text

        try:
            return call_with_retry(
                _do,
                retry_exception_types=TransientHTTPError,
                max_attempts=settings.max_retry_attempts,
                initial_wait_seconds=settings.retry_initial_wait_seconds,
                max_wait_seconds=settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise JobinjaFetchError(
                f"Could not reach Jobinja ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobinjaFetchError(f"Jobinja request failed permanently ({what}): {exc}") from exc

    # -- discovery -------------------------------------------------------
    @staticmethod
    def _extract_job_urls(listing_html: str) -> list[str]:
        """Detail URLs from one listing page, tracking params stripped.

        Returns:
            Unique URLs in document order (each job appears once per
            card; the same href can be repeated by title+logo links).
        """
        urls: list[str] = []
        seen: set[str] = set()
        for href in _JOB_URL_RE.findall(listing_html):
            url = href.split("?", 1)[0]
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    def _select_job_urls(self) -> list[str]:
        """Paginate the listing from ``start_page`` until the window fills.

        Returns:
            Up to ``max_jobs_per_run`` unique detail URLs (newest first,
            listing order). Pages beyond the last one (843+ observed
            empty) simply end the walk with whatever was collected.
        """
        settings = self._settings
        limit = settings.max_jobs_per_run
        selected: list[str] = []
        seen: set[str] = set()
        page = settings.start_page
        first_page = page

        while len(selected) < limit:
            html = self._request_text(
                settings.listing_url_template.format(page=page),
                what=f"listing page {page}",
            )
            urls = self._extract_job_urls(html)
            if not urls:
                break  # past the end of the listing
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    selected.append(url)
            page += 1
            # Pace listing reads like detail fetches: a burst of 20-40
            # back-to-back listing requests tripped jobinja's WAF into a
            # 200-status challenge page (observed 2026-10-07, mid-
            # backfill), which surfaces as zero job links.
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "Jobinja discovery selected {} unique jobs (window {}, listing pages {}-{} read).",
            len(selected),
            limit,
            first_page,
            page - 1,
        )
        return selected

    # -- detail ----------------------------------------------------------
    def _fetch_job(self, url: str) -> str | None:
        """Fetch one job page; return its HTML, or ``None`` to skip it.

        A dead/delisted link (4xx between listing read and fetch) costs
        one page, not the run — unlike a listing-page failure, which
        means discovery is broken and stays fatal via
        ``_request_text``.
        """
        try:
            return self._request_text(url, what=f"job {url.rsplit('/jobs/', 1)[-1][:40]}")
        except JobinjaFetchError as exc:
            logger.warning("Skipping Jobinja job page {}: {}", url, exc)
            return None

    # -- public entry point --------------------------------------------
    def fetch_raw_jobs(self) -> list[dict]:
        """Discover and fetch up to ``max_jobs_per_run`` job pages.

        Returns:
            Raw ``{"url": <canonical detail URL>, "html": <page>}``
            dictionaries, listing order (newest first).

        Raises:
            JobinjaFetchError: If a listing request failed after
                exhausting retries (discovery is fatal; only per-job
                pages are skippable).
            JobinjaResponseError: If discovery found zero job links, or
                every detail fetch was skipped.
        """
        selected = self._select_job_urls()
        if not selected:
            raise JobinjaResponseError(
                "Jobinja listing pages contained zero job links. The listing "
                "format may have changed, the site may be unreachable, or "
                "start_page is past the end of the listing."
            )

        settings = self._settings
        jobs: list[dict] = []
        for index, url in enumerate(selected):
            html = self._fetch_job(url)
            if html is not None:
                jobs.append({"url": url, "html": html})
            if settings.fetch_delay_seconds and index + 1 < len(selected):
                time.sleep(settings.fetch_delay_seconds)
            if (index + 1) % 50 == 0:
                logger.info(
                    "Jobinja page fetches: {}/{} (pages: {}).",
                    index + 1,
                    len(selected),
                    len(jobs),
                )

        if not jobs:
            raise JobinjaResponseError(
                "Jobinja yielded zero job pages across all fetched links. "
                "The payload shape may have changed, or the responses were "
                "blocked/empty."
            )

        logger.info(
            "Fetched {} Jobinja job pages ({} listing URLs selected).",
            len(jobs),
            len(selected),
        )
        return jobs

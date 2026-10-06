"""Fetches raw job data from Glints.

This module's only responsibility: discover job URLs via the sitemap
index, fetch each job's server-rendered page, extract the embedded
record, and hand back raw dictionaries. It does not validate individual
job fields — that is ``parser.py``'s job. Same fetch/validate/decide
separation the other scrapers establish.

Where the data lives (confirmed live, 2026-10-07)
---------------------------------------------------
Glints has no usable unauthenticated JSON API (``/api/v2/jobs`` → 401
"cookie token is empty"; GraphQL requires in-session documents), so
this client uses the two things the site *does* serve in the open:

* **Discovery — ``/sitemap_index.xml``** (~376 KB) lists ~4,942 child
  sitemaps; the job ones match ``sitemap_(sourced_)?job_{cc}_{n}.xml``
  (job_id 756 + sourced_job_id 546 + vn 55 + sg 4 + my 1 ≈ 136k
  unique jobs counting the local/en locale duplicate each URL pair
  shares). ``find_jobs_*``/``companies_*``/``category_*`` entries are
  search-landing/company pages and are deliberately excluded — a
  company sitemap looks similar but contains no job uuids.
  Within a family, sitemap #1 holds the newest postings (sampled
  2026-10-06 in ``job_id_1`` vs 2026-08-07 in ``job_id_756``); there
  is **no ``lastmod``** anywhere, so ordering is the only recency
  signal. Families are walked **round-robin** so a capped run picks up
  each country's newest jobs instead of spending its whole window on
  Indonesia's 756 sitemaps.
* **Detail — the job page itself.** Each page server-renders its full
  record in ``__NEXT_DATA__.props.pageProps.initialData.data`` (~67
  keys: title, Draft.js description, salary, location, category,
  dates). For ``/opportunities/s/``-form URLs (what
  ``sitemap_sourced_job_*`` serves) the record lives under
  ``pageProps.sourcedJob`` with only 16 keys — so the client rewrites
  ``/s/`` → ``/jobs/`` first, which serves the full record even
  though it geo-redirects the path segment (observed: ``/id/…`` →
  ``/sg/…`` from a non-ID IP). The redirect serves the *same* job —
  guarded here by checking the embedded ``id`` against the uuid in
  the URL. If that guard ever fails, the original ``/s/`` page is
  fetched and its ``sourcedJob`` accepted as the degraded fallback.

No auth, no cookies, no signing — plain GETs with a browser-style
User-Agent. ``common/http_client.py`` is GET-only with no sitemap/page
parsing, so this client does its own request loop while reusing the
shared error taxonomy (``TransientHTTPError``/``PermanentHTTPError``)
and ``call_with_retry``.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import GlintsSettings
from .exceptions import GlintsFetchError, GlintsResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: ``sitemap_job_id_12.xml``, ``sitemap_sourced_job_vn_3.xml`` — the two
#: job-sitemap families. Excludes lookalikes (``sitemap_find_jobs_*`` =
#: search-landing pages, ``sitemap_companies_*`` = company profiles).
_JOB_SITEMAP_RE = re.compile(r"^sitemap_(?:sourced_)?job_[a-z]+_\d+\.xml$")

#: The uuid is always the last path segment of a job URL.
_JOB_UUID_RE = re.compile(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$")

#: ``<script id="__NEXT_DATA__" …>{…}</script>`` — Next.js pages router
#: embeds the SSR payload here.
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


class GlintsClient:
    """Fetches the current Glints job records via sitemap + SSR pages."""

    def __init__(self, settings: GlintsSettings | None = None) -> None:
        self._settings = settings or GlintsSettings()
        # One keep-alive session: ~130k page fetches in a full crawl
        # would pay a fresh TCP+TLS handshake each without it.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
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
            raise GlintsFetchError(
                f"Could not reach Glints ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise GlintsFetchError(f"Glints request failed permanently ({what}): {exc}") from exc

    # -- discovery -------------------------------------------------------
    def _fetch_job_sitemap_families(self) -> "OrderedDict[str, list[str]]":
        """Job sitemaps from the index, grouped by family, index order.

        Returns:
            Mapping family name (e.g. ``sitemap_job_id``) → sitemap
            URLs newest-first (the index itself is ordered newest-first
            within each family — confirmed by sampling).
        """
        html = self._request_text(
            self._settings.sitemap_index_url, what="sitemap index"
        )
        locs = re.findall(r"<loc>(.*?)</loc>", html)
        families: "OrderedDict[str, list[str]]" = OrderedDict()
        for loc in locs:
            basename = loc.rsplit("/", 1)[-1]
            if not _JOB_SITEMAP_RE.match(basename):
                continue
            family = basename.rsplit("_", 1)[0]  # strip trailing _{n}.xml
            families.setdefault(family, []).append(loc)
        if not families:
            raise GlintsResponseError(
                "The Glints sitemap index contained no job sitemaps "
                "(expected entries like sitemap_job_id_1.xml). The index "
                "format may have changed."
            )
        logger.info(
            "Glints sitemap index: {} job sitemaps across {} families ({}).",
            sum(len(v) for v in families.values()),
            len(families),
            ", ".join(f"{k}={len(v)}" for k, v in families.items()),
        )
        return families

    @staticmethod
    def _job_uuid(url: str) -> str | None:
        match = _JOB_UUID_RE.search(url)
        return match.group(1) if match else None

    @staticmethod
    def _normalize_job_url(url: str) -> str:
        """``/opportunities/s/`` → ``/opportunities/jobs/`` (full record).

        See the module docstring: the ``/s/`` page only embeds the
        16-key ``sourcedJob``; the ``/jobs/`` form embeds the full
        ~67-key record for the same uuid.
        """
        return url.replace("/opportunities/s/", "/opportunities/jobs/")

    def _select_job_urls(
        self, exclude_ids: set[str] | None = None
    ) -> list[tuple[str, str]]:
        """Round-robin the families until ``max_jobs_per_run`` unique jobs.

        Args:
            exclude_ids: uuids the database already has (the pipeline
                passes ``repository.get_all_source_job_ids`` here — see
                that method's docstring). Excluded jobs cost nothing:
                they are dropped at sitemap-parse time, so a capped run
                fetches only *unseen* jobs — newest arrivals first
                (families are newest-first), then deeper into the
                corpus as known coverage grows. ``None``/empty means
                "select the newest window" (fresh scrape, ``--no-db``
                runs).

        Returns:
            Pairs of (uuid, canonical sitemap URL). The canonical URL is
            the sitemap's own (local-locale, ``/s/`` or ``/jobs/``) form —
            it is what ``original_url`` stores; fetching may rewrite it.
            When a sitemap lists the same job twice (local + ``/en/``
            locale), the local-locale URL wins.
        """
        families = self._fetch_job_sitemap_families()
        excluded = exclude_ids or set()
        limit = self._settings.max_jobs_per_run
        selected: dict[str, str] = {}
        cursors = {name: 0 for name in families}

        # One pass per family per round, taking its next unread sitemap
        # each time; stop when the window is full or a full pass makes
        # no progress (every family drained).
        while len(selected) < limit:
            progressed = False
            for name, urls in families.items():
                if len(selected) >= limit:
                    break
                cursor = cursors[name]
                if cursor >= len(urls):
                    continue
                cursors[name] = cursor + 1
                progressed = True
                for job_url in re.findall(r"<loc>(.*?)</loc>", self._request_text(
                    urls[cursor], what=f"sitemap {name} #{cursor + 1}"
                )):
                    uuid = self._job_uuid(job_url)
                    if uuid is None or uuid in excluded:
                        continue
                    existing = selected.get(uuid)
                    if existing is None:
                        selected[uuid] = job_url
                    elif "/en/" in existing and "/en/" not in job_url:
                        selected[uuid] = job_url  # prefer local locale
                    if len(selected) >= limit:
                        break
            if not progressed:
                break

        logger.info(
            "Glints discovery selected {} unique jobs (window {} from {} "
            "families, {} known excluded).",
            len(selected),
            limit,
            len(families),
            len(excluded),
        )
        return list(selected.items())

    # -- detail ----------------------------------------------------------
    @staticmethod
    def _extract_record(html: str) -> dict | None:
        """Pull the job record out of a page's ``__NEXT_DATA__`` blob."""
        match = _NEXT_DATA_RE.search(html)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            return None
        page_props = payload.get("props", {}).get("pageProps", {})
        if not isinstance(page_props, dict):
            return None
        for key in ("initialData", "sourcedJob"):
            candidate = page_props.get(key)
            if isinstance(candidate, dict):
                if key == "initialData":
                    candidate = candidate.get("data")
                if isinstance(candidate, dict) and candidate.get("id"):
                    return candidate
        return None

    def _fetch_job(self, uuid: str, canonical_url: str) -> dict | None:
        """Fetch one job page and return its embedded record.

        Tries the normalized ``/jobs/`` URL first (full record, with an
        ``id == uuid`` guard against the geo-redirect serving something
        unexpected), then falls back to the canonical ``/s/`` page's
        ``sourcedJob``. Returns ``None`` if neither yields the expected
        job — a stale sitemap entry (expired/removed job) costs one
            page, not the run.
        """
        normalized = self._normalize_job_url(canonical_url)
        html = self._request_text(normalized, what=f"job {uuid}")
        record = self._extract_record(html)
        if record is not None and str(record.get("id")) == uuid:
            return record

        if normalized != canonical_url:
            # Rewrite produced nothing usable — try the canonical /s/ page.
            html = self._request_text(canonical_url, what=f"job {uuid} (canonical)")
            record = self._extract_record(html)
            if record is not None and str(record.get("id")) == uuid:
                return record

        logger.warning(
            "Skipping Glints job {}: page did not embed the expected record "
            "(stale sitemap entry or page-shape change).",
            uuid,
        )
        return None

    # -- public entry point --------------------------------------------
    def fetch_raw_jobs(
        self, *, exclude_ids: set[str] | None = None
    ) -> list[dict]:
        """Discover and fetch up to ``max_jobs_per_run`` job pages.

        Args:
            exclude_ids: uuids to skip entirely (already in the
                database) — see ``_select_job_urls``. ``None`` selects
                the newest window.

        Returns:
            Raw job dictionaries in Glints' own field naming, each with
            ``original_url`` (the sitemap's canonical URL) injected.

        Raises:
            GlintsFetchError: If a request failed after exhausting retries.
            GlintsResponseError: If discovery or every page yielded no
                usable job records.
        """
        selected = self._select_job_urls(exclude_ids=exclude_ids)
        if not selected:
            if exclude_ids:
                # Skip-known drained every family without finding an
                # unseen uuid: the corpus is fully covered. That is a
                # successful no-op, not a discovery failure.
                logger.info(
                    "Glints discovery found no unseen jobs ({} known excluded); "
                    "corpus fully covered this run.",
                    len(exclude_ids),
                )
                return []
            raise GlintsResponseError(
                "Glints sitemap discovery returned zero job URLs. The index "
                "format may have changed, or the site may be unreachable."
            )

        settings = self._settings
        jobs: list[dict] = []
        for index, (uuid, canonical_url) in enumerate(selected):
            record = self._fetch_job(uuid, canonical_url)
            if record is not None:
                record["original_url"] = canonical_url
                jobs.append(record)
            if settings.fetch_delay_seconds and index + 1 < len(selected):
                time.sleep(settings.fetch_delay_seconds)
            if (index + 1) % 50 == 0:
                logger.info(
                    "Glints page fetches: {}/{} (records: {}).",
                    index + 1,
                    len(selected),
                    len(jobs),
                )

        if not jobs:
            raise GlintsResponseError(
                "Glints returned zero job records across all fetched pages. "
                "The payload shape may have changed, or the responses were "
                "blocked/empty."
            )

        logger.info(
            "Fetched {} Glints job records ({} pages selected).",
            len(jobs),
            len(selected),
        )
        return jobs

"""Fetches raw BongThom job records from its keyless JSON routes and pages.

This module's only responsibility: walk the open discovery paginator, then
for each row fetch its structured ``get_embed`` JSON and its server-rendered
detail page, parse the rendered "Workplace Circumstances" list into a small
dict, and hand back raw dictionaries. It does not validate individual job
fields -- that is ``parser.py``'s job. Same fetch/validate/decide separation
the other scrapers establish.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
* **Discovery** -- ``GET
  https://bongthom.com/Job_Controller/get_all?page=N`` returns the board's
  Laravel paginator envelope; ``data`` rows are the newest-first feed and
  ``per_page`` is fixed at 40. The whole board was 278 jobs over 7 pages at
  scoping.
* **Structured detail** -- ``GET
  https://bongthom.com/Job_Controller/get_embed/<id>`` returns the posting's
  content as JSON (``positions[].description``, ``duties``, ``benefits``,
  ``skill_knowledges``, ``categories``, ``qualifications`` and
  ``experiences`` with numeric ``years``).
* **Rendered detail** -- ``GET
  https://bongthom.com/job_detail/view_detail_<id>.html`` renders the
  "Workplace Circumstances" list, the only place the displayed work
  location, salary and schedule appear.

A note on the rendered page's labels
------------------------------------
Every label/value row is a ``li.clearfix.en`` regardless of the page's
display language, so a Khmer-default posting renders Khmer label text in
the same class (measured: job 42739's first six ``li.clearfix.en`` rows are
Khmer, its English rows follow). The parser therefore keeps a row only when
its ``<strong>`` label is one of the known English label strings, matching
on the label rather than trusting the class.

robots.txt posture
------------------
``https://bongthom.com/robots.txt`` (and the ``www.``/``front.`` hosts)
answer HTTP 200 with the application's HTML page under ``text/html``
instead of a policy file -- there is no robots policy to obey. The scraper
reads only the three public routes above.

Failure taxonomy, mirroring the Bdjobs/BLMIS clients:

* A **discovery page** failing after retries (transient exhaustion) or
  permanently (a non-retryable 4xx) propagates as ``BongthomFetchError``:
  without it there is nothing to sweep.
* A discovery page that is **not JSON** or has **no ``data`` list**
  propagates as ``BongthomResponseError``.
* A first page yielding **zero rows** raises ``BongthomResponseError`` --
  never a silent zero-jobs no-op.
* A **per-job** embed or rendered-page GET that fails is logged and that
  job is degraded (embed-only, or discovery-row-only) rather than aborting
  the batch.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import BongthomSettings
from .exceptions import BongthomFetchError, BongthomResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: The English "Workplace Circumstances" labels (lowercased, trailing colon
#: stripped) mapped to the raw-dict key each feeds.
_WORKPLACE_LABELS = {
    "environment": "environment",
    "languages": "languages",
    "location": "locations",
    "career category": "categories",
    "schedule": "schedule",
    "salary": "salary",
}


def _first_or_none(values: list[str]) -> str | None:
    """First value, or ``None`` for an empty list."""
    return values[0] if values else None


class BongthomClient:
    """Fetches discovery rows and hydrates each with embed + rendered page."""

    def __init__(self, settings: BongthomSettings | None = None) -> None:
        self._settings = settings or BongthomSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> BongthomClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- one retried request -------------------------------------------
    def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        what: str,
    ) -> requests.Response:
        """Send one GET with retries; classify failures into the shared taxonomy."""

        def _do() -> requests.Response:
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._settings.request_timeout_seconds,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientHTTPError(str(exc)) from exc
            except requests.RequestException as exc:
                raise PermanentHTTPError(str(exc)) from exc

            if response.status_code in _RETRYABLE_STATUS:
                raise TransientHTTPError(f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise PermanentHTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            return response

        try:
            return call_with_retry(
                _do,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise BongthomFetchError(
                f"Could not reach BongThom ({what}) after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise BongthomFetchError(
                f"BongThom request failed permanently ({what}): {exc}"
            ) from exc

    # -- discovery ------------------------------------------------------
    def _discovery_page(self, page: int) -> tuple[list[dict], int | None]:
        """GET one discovery page, returning ``(rows, last_page)``."""
        response = self._get(
            self._settings.list_url,
            params={"page": page},
            what=f"job feed page {page}",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise BongthomResponseError(
                f"BongThom job feed page {page} returned non-JSON (payload shape "
                f"change or block?): {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise BongthomResponseError(
                f"BongThom job feed page {page} returned a non-object JSON payload."
            )

        data = payload.get("data")
        if not isinstance(data, list):
            raise BongthomResponseError(
                "BongThom job feed has no usable data list (keys: "
                f"{sorted(payload)}). The payload shape may have changed."
            )
        rows = [row for row in data if isinstance(row, dict)]

        last_page: int | None = None
        raw_last = payload.get("last_page")
        try:
            last_page = int(raw_last) if raw_last is not None else None
        except (TypeError, ValueError):
            last_page = None
        return rows, last_page

    def _discover_rows(self) -> list[dict]:
        """Discovery rows from page 1 until the window fills or the feed ends."""
        settings = self._settings
        limit = settings.max_jobs_per_run
        page = 1
        selected: list[dict] = []
        seen: set[str] = set()
        last_page: int | None = None

        while len(selected) < limit and page <= settings.max_pages:
            rows, reported = self._discovery_page(page)
            if page == 1:
                if not rows:
                    raise BongthomResponseError(
                        "BongThom job feed returned zero rows on page 1. The feed "
                        "format may have changed, the site may be unreachable, or "
                        "the endpoint moved."
                    )
                last_page = reported
            elif not rows:
                break  # past the end of the feed

            for row in rows:
                job_id = str(row.get("id") or "")
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)
                selected.append(row)

            if last_page is not None and page >= last_page:
                break
            page += 1
            if settings.fetch_delay_seconds and len(selected) < limit:
                time.sleep(settings.fetch_delay_seconds)

        selected = selected[:limit]
        logger.info(
            "BongThom discovery selected {} unique rows (window {}, pages read {}).",
            len(selected),
            limit,
            page,
        )
        return selected

    # -- detail ----------------------------------------------------------
    def _fetch_embed(self, job_id: str) -> dict | None:
        """GET one structured embed; None (logged) when the call fails."""
        try:
            response = self._get(
                self._settings.embed_detail_url(job_id),
                what=f"embed {job_id}",
            )
        except BongthomFetchError as exc:
            logger.warning("Skipping BongThom embed {} (fetch failed): {}", job_id, exc)
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Skipping BongThom embed {} (non-JSON response).", job_id)
            return None
        if not isinstance(payload, dict):
            logger.warning("Skipping BongThom embed {} (non-object payload).", job_id)
            return None
        return payload

    @staticmethod
    def parse_workplace(page_html: str) -> dict:
        """Extract the English "Workplace Circumstances" rows from a detail page.

        Returns ``{"locations": [...], "salary": str | None, "schedule":
        str | None, "categories": [...], "environment": str | None,
        "languages": str | None}``. Only rows whose label is a known English
        label are kept: the site renders Khmer label text into the same
        ``li.clearfix.en`` class, so the label -- not the class -- is what
        identifies an English row.
        """
        soup = BeautifulSoup(page_html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        collected: dict[str, list[str]] = {key: [] for key in _WORKPLACE_LABELS.values()}
        for li in soup.select("li.clearfix.en"):
            strong = li.find("strong")
            value_span = li.find("span", class_=lambda c: bool(c) and "value" in c)
            if value_span is None:
                continue
            raw_label = strong.get_text(" ", strip=True) if strong else ""
            field = _WORKPLACE_LABELS.get(raw_label.strip().rstrip(":").strip().lower())
            if field is None:
                continue
            value = value_span.get_text(" ", strip=True)
            if value:
                collected[field].append(value)

        locations = list(dict.fromkeys(collected["locations"]))
        categories = list(
            dict.fromkeys(
                part.strip()
                for value in collected["categories"]
                for part in value.split(",")
                if part.strip()
            )
        )
        return {
            "locations": locations,
            "salary": _first_or_none(collected["salary"]),
            "schedule": _first_or_none(collected["schedule"]),
            "categories": categories,
            "environment": _first_or_none(collected["environment"]),
            "languages": _first_or_none(collected["languages"]),
        }

    def _fetch_workplace(self, job_id: str) -> dict:
        """GET one rendered page and parse its workplace rows; ``{}`` on failure."""
        try:
            response = self._get(
                self._settings.detail_url(job_id),
                what=f"detail page {job_id}",
            )
        except BongthomFetchError as exc:
            logger.warning("Skipping BongThom workplace {} (fetch failed): {}", job_id, exc)
            return {}
        try:
            return self.parse_workplace(response.text)
        except Exception as exc:  # noqa: BLE001 - one bad page must not abort the run
            logger.warning("Skipping BongThom workplace {} (parse failed): {}", job_id, exc)
            return {}

    def fetch_raw_jobs(self) -> list[dict]:
        """Discover the feed and hydrate each row with its embed + workplace.

        Returns:
            Raw records ``{"id": id, "listing": the discovery row dict,
            "embed": the get_embed dict or None, "workplace": the rendered
            workplace dict (possibly empty), "url": the public detail page
            URL}``.

        Raises:
            BongthomFetchError: If a discovery page GET failed after
                exhausting retries or a permanent 4xx was returned.
            BongthomResponseError: If the first page returned zero rows or
                the envelope lost its ``data`` list.
        """
        rows = self._discover_rows()

        jobs: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            job_id = str(row.get("id") or "")
            if not job_id:
                logger.warning("Skipping BongThom discovery row {}: no id.", index)
                continue
            embed = self._fetch_embed(job_id)
            workplace = self._fetch_workplace(job_id)
            jobs.append(
                {
                    "id": job_id,
                    "listing": row,
                    "embed": embed,
                    "workplace": workplace,
                    "url": self._settings.detail_url(job_id),
                }
            )
            if self._settings.fetch_delay_seconds and index + 1 < len(rows):
                time.sleep(self._settings.fetch_delay_seconds)

        logger.info(
            "Fetched {} BongThom job records ({} with embed content, {} with workplace).",
            len(jobs),
            sum(1 for job in jobs if job["embed"] is not None),
            sum(1 for job in jobs if job["workplace"]),
        )
        return jobs

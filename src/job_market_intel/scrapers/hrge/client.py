"""Fetches raw job data from HR.ge.

This module's only responsibility: make the HTTP requests (with retries
for transient failures), page through the list endpoint, optionally
enrich each listed job with its detail payload, and hand back raw
dictionaries. It does not validate individual job fields — that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-10-06/07)
-----------------------------------------------------
HR.ge (Georgia) is an Angular SSR frontend on www.hr.ge backed by a
JSON API on api.p.hr.ge (discovered via ``robots.txt``'s sitemap URL and
``assets/conf/api.json``):

* **List** — ``POST announcement-search`` with a JSON body
  ``{"announcementTypeId": 1, "start": <offset>, "limit": <=100}``
  returning ``{"success": true, "data": {"announcements": {"items":
  [...], "totalCount": N}}}``. Paging is **offset-based via ``start``**
  (a ``page`` key is accepted but ignored — it always returns page 1);
  ``limit`` above 100 is rejected with HTTP 400 "Max 100 items are
  allowed per request". Observed totals: 3,596 active vacancies
  (type 1), 5 trainings (type 3).
* **Detail** — ``GET announcement/{id}`` returning
  ``{"data": {"announcement": {...150 fields...}}}``: HTML description,
  salary, taxonomy, addresses, contacts. The slug-less public page
  ``https://www.hr.ge/announcement/{id}`` SSRs fine and is what
  ``original_url`` points humans at.

No auth, no cookies, no signing — plain JSON over GET/POST with a
browser-style User-Agent (the AWS WAF in front of the site never
challenged any probe request using one). ``Accept-Language: en`` switches
titles/taxonomy/cities to English; see ``config.py``.

``common/http_client.py`` is GET-only, so this client does its own
request loop while reusing the shared error taxonomy
(``TransientHTTPError``/``PermanentHTTPError``) and ``call_with_retry``.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import HRGeSettings
from .exceptions import HRGeFetchError, HRGeResponseError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HRGeClient:
    """Fetches the current HR.ge job records."""

    def __init__(self, settings: HRGeSettings | None = None) -> None:
        self._settings = settings or HRGeSettings()
        # One keep-alive session: a fresh TCP+TLS handshake per request
        # cost ~1.6 s/call during scoping (98 minutes for 3,596 details);
        # reusing connections brings that down to well under a second and
        # makes a full-corpus run fit in ordinary time budgets.
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.hr.ge/",
                "Origin": "https://www.hr.ge",
                "Accept-Language": self._settings.accept_language,
            }
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._session.close()

    # -- one retried request -------------------------------------------
    def _request_json(
        self,
        url: str,
        *,
        what: str,
        body: dict | None = None,
    ) -> object:
        settings = self._settings

        def _do() -> object:
            try:
                if body is None:
                    response = self._session.get(
                        url,
                        timeout=settings.request_timeout_seconds,
                    )
                else:
                    # requests sets Content-Type: application/json itself.
                    response = self._session.post(
                        url,
                        json=body,
                        timeout=settings.request_timeout_seconds,
                    )
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
            try:
                return response.json()
            except ValueError as exc:
                # An HTML challenge page or proxy error where JSON was
                # expected: treat as transient (a later attempt, or the
                # detail-skip fallback, recovers).
                raise TransientHTTPError(
                    f"non-JSON body ({response.headers.get('content-type', '?')}): "
                    f"{response.text[:120]!r}"
                ) from exc

        try:
            return call_with_retry(
                _do,
                retry_exception_types=TransientHTTPError,
                max_attempts=settings.max_retry_attempts,
                initial_wait_seconds=settings.retry_initial_wait_seconds,
                max_wait_seconds=settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise HRGeFetchError(
                f"Could not reach HR.ge ({what}) after "
                f"{settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise HRGeFetchError(f"HR.ge request failed permanently ({what}): {exc}") from exc

    # -- endpoints ------------------------------------------------------
    def _fetch_list_page(self, start: int) -> tuple[list[dict], int | None]:
        """One offset page of the vacancy list. Returns (items, totalCount)."""
        body = {
            "announcementTypeId": self._settings.announcement_type_id,
            "start": start,
            "limit": self._settings.page_size,
        }
        payload = self._request_json(
            f"{self._settings.api_base_url}announcement-search",
            what=f"list start={start}",
            body=body,
        )
        if not isinstance(payload, dict):
            raise HRGeResponseError(
                f"HR.ge list start={start} returned "
                f"{type(payload).__name__}, expected a JSON object."
            )
        data = payload.get("data")
        announcements = data.get("announcements") if isinstance(data, dict) else None
        items = announcements.get("items") if isinstance(announcements, dict) else None
        if not isinstance(items, list):
            raise HRGeResponseError(
                "HR.ge list payload has no data.announcements.items — the "
                "API's response shape may have changed."
            )
        total = announcements.get("totalCount") if isinstance(announcements, dict) else None
        clean_items = [
            item for item in items if isinstance(item, dict) and item.get("announcementId")
        ]
        return clean_items, total if isinstance(total, int) else None

    def _fetch_detail(self, announcement_id: object) -> dict | None:
        """Fetch one job's detail payload; None if it can't be fetched.

        A missing detail only costs the description/taxonomy (the list
        entry still carries title/company/location/dates), so detail
        failures are logged and skipped rather than failing the run —
        same philosophy as the parsers' skip-don't-crash behaviour. This
        also means a WAF challenge hitting only the detail endpoint
        degrades to "jobs without descriptions" instead of no run.
        """
        url = f"{self._settings.api_base_url}announcement/{announcement_id}"
        try:
            payload = self._request_json(url, what=f"detail {announcement_id}")
        except HRGeFetchError as exc:
            logger.warning("Skipping detail for HR.ge announcement {}: {}", announcement_id, exc)
            return None
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        announcement = data.get("announcement") if isinstance(data, dict) else None
        if not isinstance(announcement, dict) or not announcement.get("announcementId"):
            logger.warning("HR.ge announcement {} detail had no usable payload.", announcement_id)
            return None
        return announcement

    def _merge_detail(self, entry: dict) -> dict:
        """One list entry plus its detail payload, detail keys winning.

        Returns the entry unchanged when the detail is missing, because the list
        entry still carries title/company/location/dates on its own.
        """
        detail = self._fetch_detail(entry.get("announcementId"))
        if not detail:
            return entry
        merged = dict(entry)
        merged.update({k: v for k, v in detail.items() if v is not None})
        return merged

    # -- public entry point --------------------------------------------
    def _fetch_all_pages(self) -> tuple[list[dict], int | None]:
        """Walk the list pages, newest first, and return them with the total."""
        settings = self._settings
        listed: list[dict] = []
        total: int | None = None

        for page in range(settings.max_pages_per_run):
            start = page * settings.page_size
            items, page_total = self._fetch_list_page(start)
            if total is None:
                total = page_total
                logger.info(
                    "HR.ge reports {} announcements (type={}).",
                    total,
                    settings.announcement_type_id,
                )
            logger.info(
                "Fetching HR.ge list start={}: {} jobs (listed so far: {}).",
                start,
                len(items),
                len(listed) + len(items),
            )
            if not items:
                break
            listed.extend(items)
            if total is not None and len(listed) >= total:
                break

        return listed, total

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch up to ``max_pages_per_run`` list pages, then enrich.

        Returns:
            A list of raw job dictionaries in HR.ge's own field naming.
            Each list entry is merged with its detail payload (detail
            keys win) when ``fetch_details`` is on, so the records carry
            ``description``/``announcementRequirements``/salary.

        Raises:
            HRGeFetchError: If a request failed after exhausting retries.
            HRGeResponseError: If a payload wasn't a usable job list.
        """
        settings = self._settings
        listed, _total = self._fetch_all_pages()

        if not listed:
            raise HRGeResponseError(
                "HR.ge returned zero recognizable job records across all "
                "fetched pages. The payload shape may have changed, or this "
                "may be an empty/blocked response."
            )

        if not settings.fetch_details:
            logger.info("Fetched {} HR.ge jobs (details disabled).", len(listed))
            return listed

        # De-duplicate by id first: pages are fetched newest-first, so a
        # job posted between two page requests can appear twice and
        # would otherwise cost a second detail round-trip.
        unique: dict[str, dict] = {}
        for entry in listed:
            unique.setdefault(str(entry.get("announcementId")), entry)

        # Bound the detail phase to a budget the CI step can actually hold.
        #
        # The list phase is fast -- 3,560 announcement ids enumerated in 36
        # seconds -- but the detail phase is one HTTP request PER JOB with a
        # politeness delay between each. At the board's 3,560 live postings that
        # is several times the 20-minute step timeout, and because this loop used
        # to log nothing at all, the run looked identical to a hang: the last
        # line was "listed so far: 3560" and then 19 minutes of silence before
        # "timed out after 20 minutes".
        #
        # max_details_per_run is the real budget for one CI pass. hrge runs
        # every 12 hours, so 900/run is 1,800 details/day against a board whose
        # postings turn over far slower than that, and the newest ids -- which
        # arrive first, since pages are fetched newest-first -- are the ones
        # that get the details.
        total = len(unique)
        budget = min(total, settings.max_details_per_run)
        started = time.monotonic()
        if budget < total:
            logger.info(
                "HR.ge: {} unique postings but only fetching details for the "
                "newest {} this run (max_details_per_run).",
                total,
                budget,
            )

        enriched: list[dict] = []
        for index, entry in enumerate(unique.values()):
            if index >= budget:
                # No detail for this one; the list entry still carries
                # title/company/location/dates.
                enriched.append(entry)
                continue
            enriched.append(self._merge_detail(entry))
            if settings.detail_fetch_delay_seconds and index + 1 < budget:
                time.sleep(settings.detail_fetch_delay_seconds)
            # Progress, because this phase is minutes long and its absence is
            # what made the first diagnosis take this long.
            if (index + 1) % 100 == 0:
                logger.info(
                    "HR.ge detail fetch {}/{} ({:.0f}s elapsed).",
                    index + 1,
                    budget,
                    time.monotonic() - started,
                )

        logger.info(
            "Fetched {} HR.ge job records ({} unique, details merged for {}).",
            len(enriched),
            total,
            min(total, budget),
        )
        return enriched

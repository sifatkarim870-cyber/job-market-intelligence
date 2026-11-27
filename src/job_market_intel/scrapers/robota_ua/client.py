"""GraphQL client for Robota.ua (robota.ua, Ukraine).

One public query does everything:

  ``publishedVacancies(filter: ..., sort: BY_DATE, pagination: {page, count})``

returns the search result *with each item's full HTML description*, salary,
company, city/region, schedules, subrubrics, employment and work types, so
there is no second detail request per ad. The endpoint is
``https://dracula.robota.ua/graphql`` -- the ``graphqlApi`` value from the
site's own Angular bundle -- and it needs no key, cookie or referrer. Its
robots.txt is a generic ``User-agent: *`` group that only disallows the
``/swagger`` UI, so ``/graphql`` is allowed.

Plain ``requests`` never reaches the API: ``robota.ua`` sits behind
Cloudflare and answers HTTP 403 "Just a moment..." to a plain client.
``curl_cffi`` impersonating Chrome clears it, so every call goes through
``curl_cffi`` with the shared transient/permanent retry taxonomy. TLS
verification stays on (no ``verify=False`` anywhere), no key, no login, no
proxy.

Progress on a capped run
------------------------
The board held **97,981** postings on 2026-11-28. A CI run must not re-read
page 1 forever, so the client:

* walks newest-first (``sort: BY_DATE``),
* stops at ``max_jobs_per_run`` **unseen** ids,
* skips ``exclude_ids`` (the pipeline passes the repository's already-stored
  ids), and
* caps the walk at ``max_pages`` so a fully-covered board returns an empty
  but successful batch instead of paging through 98k rows.

A board with no usable postings at all and no exclusions raises
``RobotaUaResponseError`` (markup/query change or a block), never a silent
zero-job no-op. With exclusions present, zero unseen postings is the honest
"corpus covered" outcome and returns empty.
"""

from __future__ import annotations

import json
import time
from typing import Any

from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import RobotaUaSettings
from .exceptions import RobotaUaFetchError, RobotaUaResponseError
from .models import RawRobotaUaJob

#: Every field the parser reads. Kept as one string so a field change is one
#: edit; ``fullDescription`` is the complete HTML body (``description`` is a
#: ~250-character snippet), so it is requested alongside it as a fallback.
_VACANCY_FIELDS = """
      id
      title
      description
      fullDescription
      sortDate
      createdAt
      firstPublishedAt
      salary { amount amountFrom amountTo comment isNet currency }
      company { id name logoUrl companyUrl }
      city { id name slug region { id name } }
      address { name }
      schedules { name }
      subrubrics { id name }
      employmentTypes
      workTypes
      isActive
      anonymous
      isAgency
      formApplyCustomUrl
"""

#: The ``PublishedVacanciesFilterInput`` fields are mostly non-null booleans;
#: these values were confirmed against the live API on 2026-11-28. The three
#: "only" filters stay false so the search is the full public board, and
#: ``showWithoutSalary``/``showAgencies`` stay true so undisclosed-salary and
#: agency ads are not silently dropped.
_FILTER = (
    "showWithoutSalary:true, showAgencies:true, showOnlyNoCvApplyVacancies:false, "
    "showOnlyWithoutExperience:false, showOnlySpecialNeeds:false, showOnlyNotViewed:false, "
    "isReservation:false, isForVeterans:false, isOfficeWithGenerator:false, "
    "isOfficeWithShelter:false, militaryVacancyDisplayMode:INCLUDED"
)

#: One GraphQL document; ``.format`` doubles the literal GraphQL braces. Keeping
#: the query in one templated string makes the field list the single thing to
#: edit when the API grows a field.
_QUERY_TEMPLATE = (
    "{{ publishedVacancies(filter:{{{filter}}}, sort: BY_DATE, "
    "pagination:{{page:{page}, count:{count}}}) "
    "{{ totalCount items {{{fields}}} }} }}"
)


class RobotaUaClient:
    """Fetches public Robota.ua vacancies through the GraphQL API."""

    def __init__(self, settings: RobotaUaSettings | None = None) -> None:
        self._settings = settings or RobotaUaSettings()
        self._session = curl_requests.Session(impersonate=self._settings.impersonate)
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": self._settings.web_base_url,
                "Referer": f"{self._settings.web_base_url}/",
            }
        )

    def close(self) -> None:
        """Release the underlying curl_cffi connection pool."""
        self._session.close()

    # -- one retried GraphQL request ------------------------------------
    def _post(self, query: str):
        """POST one GraphQL query with retries; classify failures.

        Returns the curl_cffi response for HTTP 200 **and** 400 — a GraphQL
        validation error arrives as 400 with a JSON ``errors`` body, and
        ``_query`` turns it into the readable message. Other statuses are
        transport failures.
        """

        def _do():
            try:
                response = self._session.post(
                    self._settings.graphql_url,
                    data=json.dumps({"query": query}),
                    timeout=self._settings.request_timeout_seconds,
                )
            except (curl_exceptions.RequestException, curl_exceptions.CurlError) as exc:
                raise TransientHTTPError(f"transport failure talking to Robota.ua: {exc}") from exc

            if response.status_code >= 500 or response.status_code == 429:
                raise TransientHTTPError(f"Robota.ua returned HTTP {response.status_code}")
            if response.status_code not in (200, 400):
                raise PermanentHTTPError(
                    f"Robota.ua returned HTTP {response.status_code}: {response.text[:300]!r}"
                )
            return response

        return call_with_retry(
            _do,
            retry_exception_types=TransientHTTPError,
            max_attempts=self._settings.max_retry_attempts,
            initial_wait_seconds=self._settings.retry_initial_wait_seconds,
            max_wait_seconds=self._settings.retry_max_wait_seconds,
        )

    def _build_query(self, page: int, count: int) -> str:
        return _QUERY_TEMPLATE.format(
            filter=_FILTER, page=page, count=count, fields=_VACANCY_FIELDS
        )

    def _query_page(self, page: int, count: int) -> dict[str, Any]:
        """Fetch and validate one page envelope; return ``publishedVacancies``."""
        response = self._post(self._build_query(page, count))
        try:
            body = response.json()
        except ValueError as exc:
            raise RobotaUaFetchError(
                f"Robota.ua returned a non-JSON body for page {page} "
                f"(payload shape change or block?): {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise RobotaUaFetchError("Robota.ua returned a non-object JSON payload.")

        errors = body.get("errors")
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else errors
            message = first.get("message") if isinstance(first, dict) else first
            raise RobotaUaFetchError(f"Robota.ua GraphQL error: {message}")

        data = body.get("data")
        if not isinstance(data, dict):
            raise RobotaUaFetchError("Robota.ua GraphQL response has no 'data' object.")
        published = data.get("publishedVacancies")
        if not isinstance(published, dict):
            raise RobotaUaResponseError(
                "Robota.ua GraphQL response has no 'publishedVacancies' object; "
                "the query shape may have changed."
            )
        return published

    # -- discovery -------------------------------------------------------
    def fetch_raw_jobs(  # noqa: C901 - a page walk with several stop conditions
        self, exclude_ids: set[str] | None = None
    ) -> tuple[list[RawRobotaUaJob], int]:
        """Walk newest-first and return ``(jobs, pages_scraped)``.

        Args:
            exclude_ids: Already-stored ``source_job_id`` values to skip at
                selection time (the pipeline passes
                ``repository.get_all_source_job_ids``). ``None``/empty means a
                plain head-of-board window (fresh scrape, ``--no-db`` runs).

        Raises:
            RobotaUaFetchError: A request failed after retries or the body was
                not the expected JSON envelope.
            RobotaUaResponseError: Discovery yielded zero usable postings with
                no exclusion (query change / block), not an empty-but-valid
                board.
        """
        excluded = set(exclude_ids or ())
        settings = self._settings
        selected: list[RawRobotaUaJob] = []
        seen: set[str] = set()
        pages_scraped = 0
        total_count: int | None = None

        for page in range(1, settings.max_pages + 1):
            logger.info(
                "Robota.ua discovery page {} (selected {}/{} unseen, {} known excluded).",
                page,
                len(selected),
                settings.max_jobs_per_run,
                len(excluded),
            )
            published = self._query_page(page, settings.page_size)
            items = published.get("items")
            items = items if isinstance(items, list) else []
            raw_total = published.get("totalCount")
            if isinstance(raw_total, int | str) and str(raw_total).isdigit():
                total_count = int(raw_total)
            pages_scraped = page

            if not items:
                logger.info("Robota.ua page {} returned no items; stopping discovery.", page)
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    raw = RawRobotaUaJob.from_item(item, base_url=settings.web_base_url)
                except ValueError as exc:
                    logger.warning("Skipping malformed Robota.ua item: {}", exc)
                    continue
                if raw.job_id in seen or raw.job_id in excluded:
                    continue
                seen.add(raw.job_id)
                selected.append(raw)
                if len(selected) >= settings.max_jobs_per_run:
                    break

            if len(selected) >= settings.max_jobs_per_run:
                break
            if total_count is not None and page * settings.page_size >= total_count:
                break
            if settings.fetch_delay_seconds:
                time.sleep(settings.fetch_delay_seconds)

        if not selected:
            if excluded:
                logger.info(
                    "Robota.ua returned no unseen postings across {} page(s) "
                    "({} known ids excluded); the corpus is covered this run.",
                    pages_scraped,
                    len(excluded),
                )
                return [], pages_scraped
            raise RobotaUaResponseError(
                "Robota.ua publishedVacancies returned zero usable postings. "
                "The query shape may have changed, or the API was blocked."
            )

        logger.info(
            "Robota.ua discovery selected {} unseen jobs over {} page(s).",
            len(selected),
            pages_scraped,
        )
        return selected, pages_scraped

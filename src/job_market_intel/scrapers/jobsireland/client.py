"""Fetches raw postings from JobsIreland.ie (Ireland).

Plain ``requests`` -- **no browser**. Measured 2026-10-19: the site is an
Orchard CMS application and is server-rendered, so the listing fragment and the
detail page both come back complete in a plain GET.

    /Jobsireland.API/JobsIreland/BrowseJobs?page=1&pageSize=50   -> 43,925 bytes, 50 cards
    /en-US/job-Details?id=2475739                                -> 97,628 bytes

Two behaviours worth naming, both measured rather than assumed:

* **No filter parameters are sent.** The site's own ``searchVacancy()`` sends
  six filters including ``ContractTypeId=-1``, and that set returns **zero**
  cards on a 128 KB page. ``ContractTypeId=-1`` alone takes the listing from 11
  cards to 0 -- the handler reads ``-1`` as a real value, not a wildcard. So
  the client sends ``page`` and ``pageSize`` and nothing else.

* **An empty listing is retried, not believed.** Partway through a 78-page walk
  the board started answering ``0 job found`` on every parameter set, with no
  cookies set, while detail pages stayed HTTP 200. It recovered on its own.
  Retrying distinguishes that from a genuinely empty board; a single empty
  response is not treated as "the source has nothing to say".

robots.txt: ``User-agent: *``, no ``Disallow``.
"""

from __future__ import annotations

import time

import requests
from bs4 import BeautifulSoup
from loguru import logger

from .config import JobsIrelandSettings
from .exceptions import JobsIrelandFetchError, JobsIrelandResponseError


class JobsIrelandClient:
    """Fetches postings from JobsIreland.ie over plain HTTP."""

    def __init__(self, settings: JobsIrelandSettings | None = None) -> None:
        self._settings = settings or JobsIrelandSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> JobsIrelandClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- URLs ---------------------------------------------------------------

    def list_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.list_api_path}"
        return f"{base}?page={page}&pageSize={self._settings.page_size}"

    def detail_url(self, ad_id: str) -> str:
        return f"{self._settings.base_url}{self._settings.detail_path}?id={ad_id}"

    def listing_page_url(self) -> str:
        return f"{self._settings.base_url}{self._settings.listing_page_path}"

    # -- requests -----------------------------------------------------------

    def _get(self, url: str, *, ajax: bool = False) -> str:
        headers = {"X-Requested-With": "XMLHttpRequest"} if ajax else {}
        last: Exception | None = None
        for attempt in range(1, self._settings.retry_attempts + 1):
            try:
                response = self._session.get(
                    url, timeout=self._settings.timeout_seconds, headers=headers
                )
                if response.status_code == 200:
                    return response.text
                last = JobsIrelandResponseError(f"HTTP {response.status_code}")
            except requests.RequestException as exc:
                last = exc
            logger.warning(
                "jobsireland.ie attempt {}/{} failed for {}: {}",
                attempt,
                self._settings.retry_attempts,
                url[:90],
                str(last)[:110],
            )
            if attempt < self._settings.retry_attempts:
                time.sleep(self._settings.retry_backoff_seconds)
        raise JobsIrelandFetchError(
            f"jobsireland.ie request failed after {self._settings.retry_attempts} "
            f"attempts: {url[:110]} -- {last}"
        )

    def fetch_listing(self, page: int = 1) -> dict[str, dict]:
        """One page of cards from the HTML-fragment endpoint."""
        from .parser import parse_listing

        html = self._get(self.list_url(page), ajax=True)
        cards = parse_listing(html, page)
        logger.info("jobsireland.ie listing page {}: {} card(s)", page, len(cards))
        time.sleep(self._settings.inter_request_delay_seconds)
        return cards

    def _listing_is_genuinely_empty(self) -> bool:
        """Check the full listing page, which is a different code path.

        If the fragment endpoint returns nothing, the HTML page proves whether
        postings exist at all. Used to tell "the board is empty" apart from
        "this endpoint broke".
        """
        try:
            html = self._get(self.listing_page_url())
        except JobsIrelandFetchError:
            return True
        from .parser import parse_listing

        return not parse_listing(html, 1)

    def _handle_empty_listing(self, streak: int, page: int) -> tuple[bool, str | None]:
        """Decide what an empty listing page means. Returns ``(stop, failure)``.

        Split out of :meth:`discover` to keep that method inside the project's
        mccabe complexity limit.

        The board served "0 job found" for several minutes partway through a
        78-page walk, on every parameter set, with no cookies set, while detail
        pages stayed HTTP 200 -- and then recovered on its own. So an empty page
        is not evidence that the board is empty. The full HTML listing page is a
        different code path and is consulted to tell the two apart.
        """
        if streak == 1:
            genuinely_empty = self._listing_is_genuinely_empty()
            logger.info(
                "jobsireland.ie page {} returned no cards; the HTML page reports postings: {}",
                page,
                not genuinely_empty,
            )
            if genuinely_empty:
                return True, None

        if streak > self._settings.empty_listing_retries:
            logger.warning(
                "jobsireland.ie returned an empty listing {} time(s) in a row "
                "while the HTML page still shows postings -- treating this as "
                "transient and stopping.",
                streak,
            )
            return True, (
                f"empty listing on {streak} consecutive pages while the HTML page reported postings"
            )

        time.sleep(self._settings.empty_listing_backoff_seconds)
        return False, None

    def discover(self) -> tuple[dict[str, dict], dict[str, str]]:
        """Walk listing pages until the budget or the board is exhausted."""
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_list_pages + 1):
            try:
                cards = self.fetch_listing(page)
            except JobsIrelandFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobsireland.ie listing page {} failed: {}", page, exc)
                break

            if not cards:
                empty_streak += 1
                stop, failure = self._handle_empty_listing(empty_streak, page)
                if failure:
                    failures["empty_listing"] = failure
                if stop:
                    break
                continue

            empty_streak = 0
            new = 0
            for ad_id, card in cards.items():
                if ad_id not in found:
                    found[ad_id] = card
                    new += 1
            logger.info("jobsireland.ie page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found:
            raise JobsIrelandResponseError(
                "no postings discovered. This board served '0 job found' "
                "transiently during development, so an empty result is raised "
                "rather than returned -- it must not look like a successful run."
            )
        return found, failures

    def fetch_detail(self, ad_id: str) -> str | None:
        try:
            html = self._get(self.detail_url(ad_id))
        except JobsIrelandFetchError as exc:
            logger.warning("jobsireland.ie detail {} failed: {}", ad_id, exc)
            return None
        finally:
            time.sleep(self._settings.inter_request_delay_seconds)
        # A detail page for a dead id still returns 200; it just has no h3.
        if not BeautifulSoup(html, "html.parser").select_one(".job-details"):
            logger.warning("jobsireland.ie detail {} returned no .job-details block", ad_id)
            return None
        return html

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        detail_budget = self._settings.max_details_per_run or budget
        discovered, failures = self.discover()

        selected = list(discovered.items())[: min(budget, detail_budget)]
        records: list[dict] = []
        for ad_id, card in selected:
            html = self.fetch_detail(ad_id)
            if html is None:
                failures[ad_id] = "detail page unavailable or had no .job-details"
            records.append(
                {
                    "job_id": ad_id,
                    "html": html,
                    "url": self.detail_url(ad_id),
                    "listing_page": card.get("page"),
                    "hint": card,
                }
            )

        if not records:
            raise JobsIrelandResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("jobsireland.ie: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures

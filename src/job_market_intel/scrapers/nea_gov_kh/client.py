"""HTTP client for the National Employment Agency (Cambodia).

Discovery and detail both read **server-rendered HTML** on
``www.nea.gov.kh``. The bare root answers a Cloudflare JS-challenge shell to a
non-browser client, but the content paths do not: the search form and the
detail pages are ordinary HTML over ``curl_cffi`` with a Chrome
impersonation profile. The bare root is never requested, so no challenge is
ever handled or bypassed.

Discovery is a POST of the board's own search form::

    POST /vacancy/dtlSearch.do
    condDiv=SEARCH&condText=&condSort=&currentPageNo=<n>

Ten rows come back per page and each row navigates with
``fnVacancyViewNew('<32 hex>')``. Detail pages are
``GET /vacancy/view.do?condSeq=<32 hex>``.

A closed or withdrawn vacancy answers HTTP 404/410, or HTTP 200 without the
``id="vacancyTitle"`` marker; both are skipped and counted. A run that finds
no live vacancy at all raises, so a markup change cannot look like an empty
board.
"""

from __future__ import annotations

import re
import time

from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions
from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError
from job_market_intel.common.retry import call_with_retry

from .config import NeaGovKhSettings
from .exceptions import NeaGovKhFetchError, NeaGovKhResponseError

#: ``fnVacancyViewNew('<32 hex>')`` in each search result row.
_VIEW_SEQ = re.compile(r"fnVacancyViewNew\('([0-9a-f]{32})'\)")
#: The detail page's title marker (double or single quoted id).
_TITLE_MARKER = re.compile(r"""id=["']vacancyTitle["']""")

#: The board's search form, measured on 2026-11-22.
_SEARCH_FORM = {
    "condDiv": "SEARCH",
    "condText": "",
    "condSort": "",
}


class NeaGovKhClient:
    """Fetches search pages and vacancy detail pages from NEA Cambodia."""

    def __init__(self, settings: NeaGovKhSettings | None = None) -> None:
        self._settings = settings or NeaGovKhSettings()
        self._session: curl_requests.Session | None = None

    # -- session / transport ---------------------------------------------

    def _new_session(self) -> curl_requests.Session:
        return curl_requests.Session(
            impersonate=self._settings.impersonate or None,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "km-KH,km;q=0.9,en;q=0.8",
                "User-Agent": self._settings.user_agent,
            },
        )

    def _ensure_session(self) -> None:
        if self._session is None:
            self._session = self._new_session()

    def _classify(self, response: object, url: str) -> tuple[int, str]:
        status = int(getattr(response, "status_code", 0))
        text = str(getattr(response, "text", "") or "")
        if status >= 500:
            raise TransientHTTPError(f"{url} returned server error status {status}")
        if status == 429:
            raise TransientHTTPError(f"{url} returned 429 (rate limited)")
        if status >= 400 and status not in (403, 404, 410):
            raise PermanentHTTPError(f"{url} returned client error status {status}: {text[:200]!r}")
        return status, text

    def _get_once(self, url: str) -> tuple[int, str]:
        try:
            response = self._session.get(
                url,
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=True,
            )
        except (curl_exceptions.RequestException, curl_exceptions.CurlError) as exc:
            raise TransientHTTPError(f"transport failure talking to {url}: {exc}") from exc
        return self._classify(response, url)

    def _post_once(self, url: str, data: dict[str, str]) -> tuple[int, str]:
        try:
            response = self._session.post(
                url,
                data=data,
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=True,
                headers={"Referer": f"{self._settings.base_url}/vacancy/index.do"},
            )
        except (curl_exceptions.RequestException, curl_exceptions.CurlError) as exc:
            raise TransientHTTPError(f"transport failure talking to {url}: {exc}") from exc
        return self._classify(response, url)

    def _call(self, fn: object, url: str) -> tuple[int, str]:
        try:
            return call_with_retry(
                fn,  # type: ignore[arg-type]
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise NeaGovKhFetchError(
                f"NEA Cambodia unreachable after {self._settings.max_retry_attempts} "
                f"attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise NeaGovKhFetchError(f"NEA Cambodia refused {url}: {exc}") from exc

    def _get(self, url: str) -> tuple[int, str]:
        self._ensure_session()
        return self._call(lambda: self._get_once(url), url)

    def _post(self, url: str, data: dict[str, str]) -> tuple[int, str]:
        self._ensure_session()
        return self._call(lambda: self._post_once(url, data), url)

    # -- discovery -------------------------------------------------------

    def _post_search_page(self, page: int) -> tuple[int, str]:
        url = f"{self._settings.base_url}{self._settings.search_path}"
        payload = dict(_SEARCH_FORM)
        payload["currentPageNo"] = str(page)
        return self._post(url, payload)

    def discover_sequences(self, max_pages: int | None = None) -> list[str]:
        """Collect ``condSeq`` ids from the first ``max_pages`` search pages."""
        pages = self._settings.pages_per_run if max_pages is None else max_pages
        sequences: list[str] = []
        for page in range(1, pages + 1):
            status, text = self._post_search_page(page)
            if status != 200:
                raise NeaGovKhResponseError(f"NEA search page {page} returned HTTP {status}")
            found = _VIEW_SEQ.findall(text or "")
            if not found:
                logger.info(
                    "NEA search page {} returned no rows; treating it as the end of the board",
                    page,
                )
                break
            new = [seq for seq in found if seq not in sequences]
            sequences.extend(new)
            logger.info(
                "NEA search page {}: {} row(s), {} new ({} total)",
                page,
                len(found),
                len(new),
                len(sequences),
            )
            if not new:
                break
            time.sleep(self._settings.inter_request_delay_seconds)
        return sequences

    # -- detail ----------------------------------------------------------

    def _detail_url(self, sequence: str) -> str:
        return f"{self._settings.base_url}{self._settings.detail_path}?condSeq={sequence}"

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover vacancy ids, then fetch each detail page.

        Returns ``(records, failures)``. Withdrawn vacancies (HTTP 404/410 or
        a page without ``id="vacancyTitle"``) are counted and skipped, not
        recorded as failures. Raises when the run ends with no live vacancy.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}

        sequences = self.discover_sequences()
        if not sequences:
            raise NeaGovKhResponseError(
                "NEA Cambodia search returned zero vacancy ids from "
                f"{self._settings.pages_per_run} page(s). The board reported 654 "
                "vacancies on 2026-11-22, so an empty result means the search "
                "markup changed -- not that the board is empty."
            )

        records: list[dict] = []
        failures: dict[str, str] = {}
        expired = 0
        attempts = 0
        for sequence in sequences:
            if len(records) >= budget or attempts >= self._settings.max_detail_attempts:
                break
            attempts += 1
            url = self._detail_url(sequence)
            if not self._settings.fetch_details:
                records.append(
                    {
                        "job_id": sequence,
                        "html": None,
                        "url": url,
                        "listing_category": None,
                    }
                )
                continue
            try:
                status, html = self._get(url)
            except NeaGovKhFetchError as exc:
                failures[sequence] = str(exc)
                logger.warning("NEA vacancy {} failed: {}", sequence, exc)
                continue
            if status in (404, 410) or not _TITLE_MARKER.search(html or ""):
                expired += 1
                logger.debug("NEA vacancy {} is withdrawn (HTTP {})", sequence, status)
                continue
            records.append(
                {
                    "job_id": sequence,
                    "html": html,
                    "url": url,
                    "listing_category": None,
                }
            )
            time.sleep(self._settings.inter_request_delay_seconds)

        if not records:
            raise NeaGovKhResponseError(
                "NEA Cambodia discovery succeeded but no live vacancy could be "
                f"fetched ({expired} withdrawn, {len(failures)} failed) -- raised "
                "rather than returned empty."
            )
        logger.info(
            "NEA Cambodia: {} discovered, {} fetched, {} withdrawn, {} failure(s)",
            len(sequences),
            len(records),
            expired,
            len(failures),
        )
        return records, failures

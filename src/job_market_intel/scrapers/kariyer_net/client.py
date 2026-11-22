"""HTTP client for the Kariyer.net public gateways.

Two calls per posting: the search gateway lists ids, the detail gateway
returns each ad. Both speak through ``curl_cffi`` with a Chrome impersonation
profile because the detail host rejects plain ``requests`` on its TLS
fingerprint (see the config docstring). Transport failures are classified the
same way every other source in this repo classifies them -- retryable
(``TransientHTTPError``) versus permanent (``PermanentHTTPError``) -- so the
shared ``call_with_retry`` owns the backoff.
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

from .config import KariyerNetSettings
from .exceptions import KariyerNetFetchError, KariyerNetResponseError


class KariyerNetClient:
    """Fetches postings from the Kariyer.net search and detail gateways."""

    def __init__(self, settings: KariyerNetSettings | None = None) -> None:
        self._settings = settings or KariyerNetSettings()

    # -- headers ---------------------------------------------------------

    def _search_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://www.kariyer.net",
            "Referer": "https://www.kariyer.net/",
            "ClientType": "1",
        }

    def _detail_headers(self) -> dict[str, str]:
        # Deliberately no Content-Type and, critically, no ``Api-Version``:
        # adding Api-Version turns the detail gateway's 200 into a 403.
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            "Origin": "https://www.kariyer.net",
            "Referer": "https://www.kariyer.net/",
        }

    # -- transport -------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: str | None = None,
    ) -> Any:
        """Perform one gateway request and return the parsed JSON body."""

        def do_request() -> Any:
            try:
                if method == "POST":
                    response = curl_requests.post(
                        url,
                        headers=headers,
                        data=data,
                        impersonate=self._settings.impersonate or None,
                        timeout=self._settings.request_timeout_seconds,
                    )
                else:
                    response = curl_requests.get(
                        url,
                        headers=headers,
                        impersonate=self._settings.impersonate or None,
                        timeout=self._settings.request_timeout_seconds,
                    )
            except (curl_exceptions.RequestException, curl_exceptions.CurlError) as exc:
                raise TransientHTTPError(f"transport failure talking to {url}: {exc}") from exc

            if response.status_code >= 500:
                raise TransientHTTPError(
                    f"{url} returned server error status {response.status_code}"
                )
            if response.status_code == 429:
                raise TransientHTTPError(
                    f"{url} returned 429 (rate limited): {response.text[:200]!r}"
                )
            if response.status_code != 200:
                raise PermanentHTTPError(
                    f"{url} returned client error status {response.status_code}: "
                    f"{response.text[:200]!r}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise PermanentHTTPError(
                    f"{url} returned a 200 that was not valid JSON: {exc}"
                ) from exc

        try:
            return call_with_retry(
                do_request,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise KariyerNetFetchError(
                f"Kariyer.net unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise KariyerNetFetchError(f"Kariyer.net refused {url}: {exc}") from exc

    # -- endpoints -------------------------------------------------------

    def fetch_search_page(self, page: int) -> list[dict]:
        """One search window. Returns the raw ``jobSearchItem`` list."""
        url = f"{self._settings.search_base_url.rstrip('/')}{self._settings.search_path}"
        body = json.dumps({"pageNumber": page, "pageSize": self._settings.page_size})
        payload = self._request("POST", url, headers=self._search_headers(), data=body)

        if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
            keys = list(payload)[:8] if isinstance(payload, dict) else type(payload)
            raise KariyerNetResponseError(
                f"Kariyer.net search page {page} had no 'result' object (top-level keys: {keys})"
            )
        items = payload["result"].get("jobSearchItem")
        if items is None:
            raise KariyerNetResponseError(
                f"Kariyer.net search page {page} had no 'jobSearchItem' key "
                f"(result keys: {list(payload['result'])[:8]})"
            )
        return list(items)

    def fetch_detail(self, job_id: str) -> dict:
        """The detail document's ``data`` object for one ad.

        Tries the configured detail host first (the non-PX ``api-web`` mirror),
        then the PX-fronted ``...V4`` host the SPA itself calls. The mirror
        answered 15/15 on 2026-11-22 while the PX host intermittently 403'd, so
        the order matters; the fallback exists so one host's bad day is not a
        failed run.
        """
        bases: list[str] = []
        for base in (
            self._settings.detail_base_url,
            self._settings.detail_fallback_base_url,
        ):
            base = (base or "").strip()
            if base and base not in bases:
                bases.append(base)

        last_error: KariyerNetFetchError | None = None
        for base in bases:
            url = f"{base.rstrip('/')}{self._settings.detail_path}?jobId={job_id}"
            try:
                payload = self._request("GET", url, headers=self._detail_headers())
            except KariyerNetFetchError as exc:
                last_error = exc
                logger.warning(
                    "Kariyer.net detail host {} failed for jobId={}: {}",
                    base,
                    job_id,
                    exc,
                )
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                last_error = KariyerNetResponseError(
                    f"Kariyer.net detail for jobId={job_id} had no 'data' object "
                    f"(top-level keys: "
                    f"{list(payload)[:8] if isinstance(payload, dict) else type(payload)})"
                )
                continue
            return payload["data"]

        if last_error is not None:
            raise last_error
        raise KariyerNetResponseError(
            f"Kariyer.net has no detail host configured for jobId={job_id}"
        )

    # -- mapping ---------------------------------------------------------

    def _merge(self, listing_item: dict, detail: dict, page: int) -> dict:
        """Flatten one listing item plus its detail document into a raw record."""
        general = detail.get("jobGeneralInformation") or {}
        position = detail.get("jobPositionInformation") or {}
        criteria = detail.get("jobCandidateCriteria") or {}
        company = detail.get("jobCompanyInformation") or {}

        job_id = general.get("id") or listing_item.get("jobId")
        title = general.get("title") or listing_item.get("title")

        job_path = general.get("jobUrl") or listing_item.get("detailUrl") or ""
        job_url = f"{self._settings.site_base_url.rstrip('/')}{job_path}" if job_path else None

        description_html = general.get("qualificationsWithHtml")
        description_text = general.get("qualifications")

        closing = general.get("closingDateNumeric") or general.get("closingDate")
        posting = general.get("postingDate") or listing_item.get("postingDate")

        company_name = (
            company.get("companyName") or listing_item.get("companyName") or "Unknown employer"
        )
        logo = (
            general.get("logoUrlFullPath")
            or general.get("squareLogoUrl")
            or general.get("logoUrl")
            or listing_item.get("squareLogoUrl")
            or listing_item.get("logoUrl")
            or None
        )

        sectors = position.get("sectors") or []
        sector_names = [
            str(item.get("name")) for item in sectors if isinstance(item, dict) and item.get("name")
        ]
        company_sector = company.get("companySector")
        if isinstance(company_sector, list):
            company_sector = ", ".join(str(s) for s in company_sector if s)
        elif company_sector is not None:
            company_sector = str(company_sector)

        category_parts = [
            position.get("positionNameEn"),
            position.get("positionName"),
            *sector_names,
        ]
        job_category_raw = " ".join(str(p) for p in category_parts if p) or listing_item.get(
            "title"
        )
        if company_sector:
            job_category_raw = f"{job_category_raw} {company_sector}".strip()

        return {
            "source_job_id": str(job_id),
            "title": title,
            "company_name": company_name,
            "company_logo_url": logo,
            "location_text": self._location_text(general, listing_item),
            "description_html": description_html,
            "description_text": description_text or general.get("jobDescription"),
            "posting_date": posting,
            "closing_date": closing,
            "job_url": job_url,
            "employment_type_raw": position.get("workType"),
            "employment_type_text": (
                position.get("workTypeText") or listing_item.get("positionTypeText")
            ),
            "work_model_raw": position.get("workModel"),
            "is_remote_work": position.get("isRemoteWork"),
            "position_level_text": position.get("positionLevelText"),
            "education_level_text": criteria.get("educationLevelText"),
            "experience_text": criteria.get("experienceText"),
            "job_category_raw": job_category_raw,
            "company_sector": company_sector,
            "salary_budget": detail.get("jobSalaryBudget"),
            "listing_page": page,
            "raw": {
                "listing": listing_item,
                "jobGeneralInformation": general,
                "jobPositionInformation": position,
                "jobCandidateCriteria": criteria,
                "jobCompanyInformation": company,
                "jobSalaryBudget": detail.get("jobSalaryBudget"),
                "breadCrumb": detail.get("breadCrumb"),
                "redirectedJobInformation": detail.get("redirectedJobInformation"),
            },
        }

    def _location_text(self, general: dict, listing_item: dict) -> str | None:
        """``"<city>, <country>"`` from the detail ``locations`` list."""
        locations = general.get("locations") or []
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            city = str(loc.get("cityName") or "").strip()
            country = str(loc.get("countryName") or "").strip()
            parts = [part for part in (city, country) if part]
            if parts:
                return ", ".join(parts)
        return general.get("locationText") or listing_item.get("locationText")

    # -- orchestration ---------------------------------------------------

    def discover_job_ids(self) -> dict[str, dict]:
        """Walk the search windows and return ``{job_id: listing_item}``.

        De-duplication by ``jobId`` is mandatory here, not a nicety: the
        gateway's page windows overlap and rotate, so the same ad is served on
        several pages (measured 2026-11-22).
        """
        collected: dict[str, dict] = {}
        for page in range(1, self._settings.max_pages_per_run + 1):
            try:
                items = self.fetch_search_page(page)
            except KariyerNetFetchError as exc:
                logger.warning("Kariyer.net search page {} failed: {}", page, exc)
                break
            if not items:
                logger.info("Kariyer.net search exhausted at page {}", page)
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                job_id = item.get("jobId")
                if job_id is None:
                    continue
                collected.setdefault(str(job_id), {**item, "_page": page})
            logger.info(
                "Kariyer.net search page {}: {} item(s), {} unique so far",
                page,
                len(items),
                len(collected),
            )
            if len(collected) >= self._settings.max_jobs_per_run:
                break
            if page < self._settings.max_pages_per_run:
                time.sleep(self._settings.inter_request_delay_seconds)
        return collected

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover ids, then fetch each ad's detail document.

        Returns ``(records, failures)``. A failed detail call is recorded and
        skipped rather than turned into a half-record -- the listing alone has
        no body text, so a record without its detail would be empty.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}

        discovered = self.discover_job_ids()
        if not discovered:
            raise KariyerNetResponseError(
                "Kariyer.net search returned zero postings. The board published "
                "22,696 live ads on 2026-11-22, so an empty result means the "
                "gateway or its response shape changed -- not that the board is empty."
            )

        records: list[dict] = []
        failures: dict[str, str] = {}
        for job_id, listing_item in list(discovered.items()):
            if len(records) >= budget:
                break
            if not self._settings.fetch_details:
                records.append(self._merge(listing_item, {}, listing_item.get("_page", 0)))
                continue
            try:
                detail = self.fetch_detail(job_id)
            except KariyerNetFetchError as exc:
                failures[job_id] = str(exc)
                logger.warning("Kariyer.net detail {} failed: {}", job_id, exc)
                continue
            record = self._merge(listing_item, detail, listing_item.get("_page", 0))
            if not record.get("title"):
                failures[job_id] = "detail document had no title"
                continue
            records.append(record)
            time.sleep(self._settings.inter_request_delay_seconds)

        if not records and not failures:
            raise KariyerNetResponseError(
                "Kariyer.net discovery succeeded but no ad could be assembled -- "
                "raised rather than returned empty."
            )
        logger.info(
            "Kariyer.net: {} unique id(s) discovered, {} record(s) fetched, {} failure(s)",
            len(discovered),
            len(records),
            len(failures),
        )
        return records, failures

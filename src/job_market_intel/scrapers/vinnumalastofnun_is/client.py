"""Fetches raw postings from island.is for Vinnumalastofnun (Iceland).

Discovery is one persisted Apollo GraphQL query
(``GetGenericListItems``) against ``https://island.is/api/graphql``. The
non-obvious step is that Apollo's CSRF filter rejects a GET without a
non-simple ``Content-Type``; sending ``Content-Type: application/json`` (the
same header the island.is front-end sends) is what makes the query answer HTTP
200 instead of a 400 "potential Cross-Site Request Forgery" error.

The detail is the public ad page ``/s/vinnumalastofnun/laus-storf/{slug}``.
It is server rendered, but the body lives in the Next.js ``__NEXT_DATA__``
blob: ``props.pageProps.apolloState`` holds a ``GenericListItem`` whose
``content`` list references ``Html`` nodes. Reading those nodes gives the full
description without a browser, one request per vacancy.

A failed detail page is not fatal: the list item still carries the title,
employer, deadline and tags, so the parser falls back to the item's card intro
and the row stays useful. The failure is recorded and counted.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests
from loguru import logger

from .config import VinnumalastofnunIsSettings
from .exceptions import (
    VinnumalastofnunIsFetchError,
    VinnumalastofnunIsResponseError,
)
from .models import RawVinnumalastofnunIsJob
from .parser import normalize_description, rich_text_to_text

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class VinnumalastofnunIsClient:
    """Fetches the GraphQL listing pages and the ad pages they point at."""

    def __init__(self, settings: VinnumalastofnunIsSettings | None = None) -> None:
        self._settings = settings or VinnumalastofnunIsSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "*/*",
                # Apollo's CSRF filter refuses a GET without a non-simple
                # Content-Type; this is the header the front-end sends.
                "Content-Type": "application/json",
                "apollo-require-preflight": "true",
                "apollographql-client-name": "cms-web-client",
                "apollographql-client-version": "0.1",
                "Accept-Language": "is,en;q=0.8",
                "Referer": self._settings.listing_page_url,
            }
        )
        self._last_request_at: float | None = None

    # -- transport ---------------------------------------------------------

    def _throttle(self) -> None:
        """Polite gap between any two requests (no robots file sets a delay)."""
        if self._last_request_at is None or self._settings.inter_request_delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.inter_request_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(self, url: str, *, accept: str) -> requests.Response:
        """One GET with bounded backoff; returns the response for any <500.

        Transport errors and 5xx answers are retried; a 4xx answer is returned
        to the caller, which knows whether that status is meaningful.
        """
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds
        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            try:
                response = self._session.get(
                    url,
                    headers={"Accept": accept},
                    timeout=self._settings.request_timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "island.is request {}/{} failed for {}: {}",
                    attempt,
                    self._settings.max_retry_attempts,
                    url[:120],
                    type(exc).__name__,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue
            finally:
                self._last_request_at = time.monotonic()

            if response.status_code >= 500:
                last_error = VinnumalastofnunIsFetchError(f"HTTP {response.status_code} for {url}")
                logger.warning(
                    "island.is answered HTTP {} for {} (attempt {}/{})",
                    response.status_code,
                    url[:120],
                    attempt,
                    self._settings.max_retry_attempts,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue
            return response

        raise VinnumalastofnunIsFetchError(
            f"island.is refused {url[:120]}: {last_error}"
        ) from last_error

    # -- listing -----------------------------------------------------------

    def build_list_url(self, page: int) -> str:
        """The persisted-query GET URL for one listing page (1-based)."""
        variables = {
            "input": {
                "genericListId": self._settings.generic_list_id,
                "size": self._settings.page_size,
                "lang": "is",
                "page": page,
                "queryString": "",
                "tags": [],
                "orderBy": "PUBLISH_DATE",
            }
        }
        extensions = {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": self._settings.persisted_query_hash,
            }
        }
        encoded_variables = requests.utils.quote(
            json.dumps(variables, separators=(",", ":")), safe=""
        )
        encoded_extensions = requests.utils.quote(
            json.dumps(extensions, separators=(",", ":")), safe=""
        )
        return (
            f"{self._settings.graphql_url}?operationName=GetGenericListItems"
            f"&variables={encoded_variables}&extensions={encoded_extensions}"
        )

    def search_page(self, page: int) -> dict[str, Any]:
        """Fetch one listing page and return the ``getGenericListItems`` object."""
        response = self._request(self.build_list_url(page), accept="application/json")
        if response.status_code == 400:
            raise VinnumalastofnunIsResponseError(
                f"island.is GraphQL page {page} answered HTTP 400 "
                "(Apollo's CSRF filter or a rotated persisted-query hash); "
                "the listing contract changed."
            )
        if response.status_code != 200:
            raise VinnumalastofnunIsResponseError(
                f"island.is GraphQL page {page} answered HTTP {response.status_code}."
            )
        try:
            document = response.json()
        except ValueError as exc:
            raise VinnumalastofnunIsResponseError(
                f"island.is GraphQL page {page} was not JSON: {exc}"
            ) from exc

        errors = document.get("errors") if isinstance(document, dict) else None
        if errors:
            raise VinnumalastofnunIsResponseError(
                f"island.is GraphQL page {page} returned errors: {str(errors)[:300]}"
            )
        data = (document.get("data") or {}).get("getGenericListItems")
        if not isinstance(data, dict) or "items" not in data:
            raise VinnumalastofnunIsResponseError(
                f"island.is GraphQL page {page} carried no getGenericListItems.items; "
                "the API shape changed."
            )
        return data

    def fetch_all_list_items(self) -> tuple[list[dict[str, Any]], int, int]:
        """Walk every listing page, de-duplicated by id.

        Returns ``(items, total, pages_fetched)``. The board is measured at 26
        vacancies, so this is normally one request; the loop exists so growth
        is handled rather than silently truncated.
        """
        first = self.search_page(1)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        total = int(first.get("total") or 0)
        pages_fetched = 1

        def absorb(page_items: list[Any]) -> None:
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id") or "").strip()
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)
                items.append(item)

        absorb(first.get("items") or [])
        if total <= 0 and not items:
            raise VinnumalastofnunIsResponseError(
                "island.is GetGenericListItems returned no items and total=0. "
                "The board measured 26 vacancies on 2026-11-28, so an empty result "
                "means the persisted-query id or the API shape changed -- not that "
                "the board is empty."
            )

        pages_available = (
            (total + self._settings.page_size - 1) // self._settings.page_size if total else 1
        )
        pages_to_scan = min(max(pages_available, 1), self._settings.max_pages_scanned)
        for page in range(2, pages_to_scan + 1):
            document = self.search_page(page)
            pages_fetched += 1
            page_items = document.get("items") or []
            if not page_items:
                break
            absorb(page_items)
            if len(items) >= total > 0:
                break

        return items, total, pages_fetched

    # -- detail ------------------------------------------------------------

    @staticmethod
    def _apollo_state(page_html: str) -> dict[str, Any] | None:
        """Extract ``props.pageProps.apolloState`` from a Next.js page."""
        match = _NEXT_DATA.search(page_html)
        if not match:
            return None
        try:
            document = json.loads(match.group(1))
        except ValueError:
            return None
        props = document.get("props") or {}
        page_props = props.get("pageProps") or {}
        if not isinstance(page_props, dict):
            return None
        apollo = page_props.get("apolloState")
        if apollo is None:
            nested = page_props.get("pageProps")
            if isinstance(nested, dict):
                apollo = nested.get("apolloState")
        return apollo if isinstance(apollo, dict) else None

    def fetch_detail(self, job_id: str, slug: str) -> dict[str, Any]:
        """Fetch one ad page and return its description body."""
        url = self._settings.detail_url_template.format(slug=slug)
        response = self._request(url, accept="text/html")
        if response.status_code in (404, 410):
            raise VinnumalastofnunIsFetchError(f"HTTP {response.status_code} for {url}")
        if response.status_code != 200:
            raise VinnumalastofnunIsFetchError(f"HTTP {response.status_code} for {url}")

        apollo = self._apollo_state(response.text)
        if not apollo:
            raise VinnumalastofnunIsResponseError(
                f"island.is ad {job_id} carried no __NEXT_DATA__ apolloState."
            )

        entry = apollo.get(f"GenericListItem:{job_id}")
        if not isinstance(entry, dict):
            entry = next(
                (
                    value
                    for key, value in apollo.items()
                    if key.startswith("GenericListItem:")
                    and isinstance(value, dict)
                    and value.get("id") == job_id
                ),
                None,
            )
        if not isinstance(entry, dict):
            raise VinnumalastofnunIsResponseError(
                f"island.is ad {job_id} had no GenericListItem in its apolloState."
            )

        chunks: list[str] = []
        for reference in entry.get("content") or []:
            ref_id = reference.get("__ref") if isinstance(reference, dict) else None
            node = apollo.get(ref_id) if isinstance(ref_id, str) else None
            if isinstance(node, dict) and node.get("document"):
                text = rich_text_to_text(node["document"])
                if text:
                    chunks.append(text)

        body = normalize_description("\n\n".join(chunks))
        return {
            "body": body,
            "content_blocks": len(chunks),
            "full_width_image_in_content": entry.get("fullWidthImageInContent"),
        }

    # -- orchestration -----------------------------------------------------

    def fetch_raw_jobs(
        self, max_jobs: int | None = None
    ) -> tuple[list[RawVinnumalastofnunIsJob], dict[str, str], int, int]:
        """Read the listing and fetch each vacancy's ad page.

        Returns ``(raw_jobs, failures, total_results, pages_scanned)``.
        ``failures`` maps a failed detail URL to the reason; the list item is
        still returned as a record (with ``detail=None``) because it carries
        enough fields to be useful.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], {}, 0, 0

        items, total, pages_fetched = self.fetch_all_list_items()
        records: list[RawVinnumalastofnunIsJob] = []
        for position, item in enumerate(items):
            if len(records) >= budget:
                break
            job_id = str(item.get("id") or "").strip()
            slug = str(item.get("slug") or "").strip()
            if not job_id or not slug:
                continue
            records.append(
                RawVinnumalastofnunIsJob(
                    job_id=job_id,
                    slug=slug,
                    url=self._settings.detail_url_template.format(slug=slug),
                    list_position=position,
                    list_total=total,
                    list_item=item,
                )
            )

        if not records:
            raise VinnumalastofnunIsResponseError(
                "island.is discovery succeeded but no vacancy was collected -- "
                "raised rather than returned empty."
            )

        if not self._settings.fetch_details:
            logger.info(
                "Vinnumalastofnun: total={}, pages fetched={}, {} list rows (details skipped)",
                total,
                pages_fetched,
                len(records),
            )
            return records, {}, total, pages_fetched

        failures: dict[str, str] = {}
        with_detail: list[RawVinnumalastofnunIsJob] = []
        for record in records:
            try:
                detail = self.fetch_detail(record.job_id, record.slug)
            except (VinnumalastofnunIsFetchError, VinnumalastofnunIsResponseError) as exc:
                failures[record.url] = str(exc)
                logger.warning("island.is ad {} failed: {}", record.job_id, exc)
                with_detail.append(record)
                continue
            with_detail.append(record.model_copy(update={"detail": detail}))

        logger.info(
            "Vinnumalastofnun: total={}, pages fetched={}, {} rows, {} detail failure(s)",
            total,
            pages_fetched,
            len(with_detail),
            len(failures),
        )
        return with_detail, failures, total, pages_fetched

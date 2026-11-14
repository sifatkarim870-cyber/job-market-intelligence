"""HTTP client for the Ajira Portal Tanzania GraphQL API."""
from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import AjiraTzSettings
from .exceptions import AjiraTzFetchError

logger = logging.getLogger(__name__)

_LIST_QUERY = """
query GetVacancies {
    getVacancies {
        id
        openDate
        closeDate
        noOfPost
        vacancyStatus { statusText }
    }
}
"""

_DETAIL_QUERY = """
query GetVacancy($vacancyId: Int!) {
    getVacancy(vacancyId: $vacancyId) {
        id
        openDate
        closeDate
        noOfPost
        scheme {
            id
            codeNo
            dutiesResponsibilities
            qualifications
            salaryScale { id name }
            emp { id name }
        }
        vacancyStatus { statusText }
    }
}
"""

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://portal.ajira.go.tz",
    "Referer": "https://portal.ajira.go.tz/vacancies",
    "User-Agent": "Mozilla/5.0 (compatible; job-market-research-bot/1.0)",
}


class AjiraTzClient:
    """Thin GraphQL client for portal.ajira.go.tz."""

    def __init__(self, settings: AjiraTzSettings | None = None) -> None:
        self._s = settings or AjiraTzSettings()
        self._ssl_ctx = ssl.create_default_context()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a single GraphQL POST request."""
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._s.graphql_url, data=data, headers=_HEADERS, method="POST"
        )
        try:
            with urllib.request.urlopen(
                req, context=self._ssl_ctx, timeout=self._s.request_timeout
            ) as resp:
                body = resp.read()
        except Exception as exc:
            raise AjiraTzFetchError(f"Request to {self._s.graphql_url} failed: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AjiraTzFetchError(f"Non-JSON response: {body[:200]}") from exc

        if "errors" in parsed:
            raise AjiraTzFetchError(f"GraphQL errors: {parsed['errors']}")

        return parsed.get("data", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_vacancy_list(self) -> list[dict[str, Any]]:
        """Return lightweight list of all vacancies from getVacancies."""
        logger.info("Fetching vacancy listing from Ajira TZ …")
        data = self._post({"query": _LIST_QUERY})
        vacancies = data.get("getVacancies") or []
        logger.info("Got %d vacancies from listing", len(vacancies))
        return vacancies

    def fetch_vacancy_detail(self, vacancy_id: int) -> dict[str, Any]:
        """Return full detail for a single vacancy."""
        data = self._post(
            {"query": _DETAIL_QUERY, "variables": {"vacancyId": vacancy_id}}
        )
        return data.get("getVacancy") or {}

    def fetch_all_details(
        self, vacancy_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        """Concurrently fetch details for multiple vacancies."""
        results: dict[int, dict[str, Any]] = {}
        logger.info(
            "Fetching details for %d vacancies (concurrency=%d) …",
            len(vacancy_ids),
            self._s.detail_concurrency,
        )
        with ThreadPoolExecutor(max_workers=self._s.detail_concurrency) as pool:
            future_map = {
                pool.submit(self.fetch_vacancy_detail, vid): vid
                for vid in vacancy_ids
            }
            for future in as_completed(future_map):
                vid = future_map[future]
                try:
                    results[vid] = future.result()
                    logger.debug("Detail fetched for vacancy %d", vid)
                except AjiraTzFetchError as exc:
                    logger.warning("Could not fetch detail for vacancy %d: %s", vid, exc)
        return results

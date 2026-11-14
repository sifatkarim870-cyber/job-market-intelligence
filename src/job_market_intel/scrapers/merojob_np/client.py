"""HTTP client for Merojob (Nepal) public REST API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from loguru import logger

from .config import MerojobSettings
from .exceptions import MerojobAPIError


class MerojobClient:
    """Client for querying Merojob jobs listing and detail endpoints."""

    def __init__(self, settings: MerojobSettings | None = None) -> None:
        self.settings = settings or MerojobSettings()

    def _get(self, url: str) -> dict[str, Any]:
        """Make an HTTP GET request and parse the JSON response."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            raise MerojobAPIError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise MerojobAPIError(f"Network error fetching {url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise MerojobAPIError(f"Invalid JSON returned from {url}: {exc}") from exc
        except Exception as exc:
            raise MerojobAPIError(f"Unexpected error fetching {url}: {exc}") from exc

    def fetch_job_listings(self) -> list[dict[str, Any]]:
        """Fetch all currently active jobs from Merojob."""
        logger.info("Fetching Merojob active jobs list from {}", self.settings.jobs_endpoint)
        data = self._get(self.settings.jobs_endpoint)
        results = data.get("results")
        if isinstance(results, list):
            logger.info("Merojob returned {} active job records.", len(results))
            return results
        logger.warning("Merojob endpoint did not return a results list: {}", data)
        return []

    def fetch_job_detail(self, job_id: int) -> dict[str, Any] | None:
        """Fetch full vacancy details for a single job id."""
        url = self.settings.job_detail_endpoint_template.format(job_id=job_id)
        try:
            return self._get(url)
        except MerojobAPIError as exc:
            logger.warning("Failed to fetch detail for job {}: {}", job_id, exc)
            return None

    def fetch_all_details(
        self, job_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        """Fetch details for a list of job ids with rate limiting."""
        details: dict[int, dict[str, Any]] = {}
        logger.info("Fetching details for {} Merojob vacancies...", len(job_ids))
        for idx, jid in enumerate(job_ids, 1):
            detail = self.fetch_job_detail(jid)
            if detail:
                details[jid] = detail
            if self.settings.rate_limit_delay > 0 and idx < len(job_ids):
                time.sleep(self.settings.rate_limit_delay)
        logger.info("Successfully retrieved {} details.", len(details))
        return details

"""HTTP client for The Muse public jobs API.

Page-based pagination here (unlike Himalayas, whose ``page`` is ignored).
Requests are retried with exponential backoff on transport errors, 429 and 5xx;
anything else 4xx is raised as permanent rather than retried.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from job_market_intel.scrapers.themuse.config import ThemuseSettings
from job_market_intel.scrapers.themuse.exceptions import (
    ThemuseError,
    ThemusePermanentError,
)


class ThemuseClient:
    """Fetches job records from The Muse public API."""

    def __init__(self, settings: ThemuseSettings | None = None) -> None:
        self.settings = settings or ThemuseSettings()

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk ``max_pages_per_run`` pages, deduplicated by ``id``.

        Duplicate ids across pages are expected: a posting republished by its
        employer can appear on more than one page, and handing it to the
        repository twice would inflate every counter in the run summary.
        """
        collected: dict[str, dict] = {}

        for page in range(1, self.settings.max_pages_per_run + 1):
            jobs = self.fetch_page(page)
            if not jobs:
                logger.info("The Muse feed is empty at page {}; stopping", page)
                break
            for job in jobs:
                ident = job.get("id")
                if ident is None:
                    # Without an identity there is no deduplication; skipping
                    # beats inventing an id that would collide with a real one.
                    continue
                collected[str(ident)] = job

        logger.info("The Muse fetched {} unique postings", len(collected))
        return list(collected.values())

    def fetch_page(self, page: int) -> list[dict]:
        """One page of the job list; empty when past the end."""
        url = f"{self.settings.base_url.rstrip('/')}{self.settings.jobs_path}"
        params = {"page": page, "page_size": self.settings.page_size}

        response = self._request(url, params)
        if response is None:
            return []
        try:
            payload = response.json()
        except ValueError as exc:
            raise ThemusePermanentError(
                f"The Muse returned non-JSON at page {page}: {response.text[:120]!r}"
            ) from exc

        results = payload.get("results") if isinstance(payload, dict) else None
        if results is None:
            keys = list(payload)[:8] if isinstance(payload, dict) else type(payload)
            raise ThemusePermanentError(
                f"no 'results' key in The Muse response at page {page}; keys were {keys}"
            )
        return list(results)

    def _request(self, url: str, params: dict) -> requests.Response | None:
        attempts = self.settings.max_retries + 1
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.settings.request_timeout_seconds,
                    headers={
                        "User-Agent": self.settings.user_agent,
                        "Accept": "application/json",
                    },
                )
            except requests.RequestException as exc:
                # requests.RequestException is the base for ConnectionError,
                # Timeout and friends; catching subclasses individually is how
                # a transport failure went unretried in the jobam client.
                last = exc
                logger.warning(
                    "The Muse transport error (attempt {}/{}): {}",
                    attempt,
                    attempts,
                    str(exc)[:110],
                )
            else:
                if response.status_code == 200:
                    return response
                if response.status_code == 429 or response.status_code >= 500:
                    last = ThemuseError(f"HTTP {response.status_code} from The Muse")
                    logger.warning(
                        "The Muse HTTP {} (attempt {}/{})",
                        response.status_code,
                        attempt,
                        attempts,
                    )
                else:
                    raise ThemusePermanentError(
                        f"The Muse returned HTTP {response.status_code} for {params}"
                    )

            if attempt < attempts:
                time.sleep(self.settings.retry_backoff_seconds * (2 ** (attempt - 1)))

        logger.error("The Muse request failed after {} attempts: {}", attempts, last)
        return None

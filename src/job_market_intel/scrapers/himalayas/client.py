"""HTTP client for the Himalayas jobs API.

Retries transient failures with exponential backoff. The distinction that
matters here: a transport error or a 5xx is worth retrying, a 4xx is not --
retrying a 404 ten times just delays the failure and hides it.
"""

from __future__ import annotations

import time

import requests
from loguru import logger

from job_market_intel.scrapers.himalayas.config import HimalayasSettings
from job_market_intel.scrapers.himalayas.exceptions import HimalayasError


#: Raised by the client and understood by the pipeline as "stop, do not retry".
class HimalayasPermanentError(HimalayasError):
    """A request that will not succeed on retry (4xx other than 429)."""


class HimalayasClient:
    """Fetches job records from the Himalayas public API."""

    def __init__(self, settings: HimalayasSettings | None = None) -> None:
        self.settings = settings or HimalayasSettings()

    def fetch_page(self, offset: int) -> list[dict]:
        """One offset window of the job list.

        Returns an empty list at the end of the feed rather than raising: a
        board with fewer postings than the cap is the normal case on a small
        aggregator, and treating "ran out" as a failure would turn a healthy
        run red.
        """
        url = f"{self.settings.base_url.rstrip('/')}{self.settings.jobs_path}"
        params = {"limit": self.settings.page_size, "offset": offset}

        response = self._request(url, params)
        if response is None:
            return []
        try:
            payload = response.json()
        except ValueError as exc:
            raise HimalayasPermanentError(
                f"Himalayas returned non-JSON at offset {offset}: {response.text[:120]!r}"
            ) from exc

        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if jobs is None:
            raise HimalayasPermanentError(
                f"no 'jobs' key in Himalayas response at offset {offset}; "
                f"keys were {list(payload)[:8] if isinstance(payload, dict) else type(payload)}"
            )
        return list(jobs)

    def fetch_raw_jobs(self) -> list[dict]:
        """Walk the configured number of offset windows.

        Duplicates are dropped by ``guid``: the API re-serves postings that
        straddle an offset boundary, and without this the same job would be
        handed to the repository twice in one run (harmless for dedup, but it
        inflates every counter in the run summary).
        """
        collected: dict[str, dict] = {}
        for page in range(self.settings.max_pages_per_run):
            offset = page * self.settings.page_size
            try:
                jobs = self.fetch_page(offset)
            except HimalayasPermanentError:
                raise
            except HimalayasError as exc:
                logger.warning("Himalayas offset {} failed: {}", offset, exc)
                break

            if not jobs:
                logger.info("Himalayas feed exhausted at offset {}", offset)
                break

            for job in jobs:
                guid = job.get("guid")
                if not guid:
                    # No stable identity means no deduplication; skipping is
                    # better than inventing an id that would collide.
                    continue
                collected[str(guid)] = job

            if len(jobs) < self.settings.page_size:
                logger.info("Himalayas returned a short page at offset {}; stopping", offset)
                break

        logger.info("Himalayas fetched {} unique postings", len(collected))
        return list(collected.values())

    def _request(self, url: str, params: dict) -> requests.Response | None:
        attempts = self.settings.max_retries + 1
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.settings.request_timeout_seconds,
                    headers={"User-Agent": self.settings.user_agent, "Accept": "application/json"},
                )
            except requests.RequestException as exc:
                # requests.RequestException is the base for ConnectionError,
                # Timeout and every RequestsError-shaped failure; catching the
                # concrete subclasses individually is what let a transport
                # failure escape unretried elsewhere in this codebase.
                last = exc
                logger.warning(
                    "Himalayas transport error (attempt {}/{}): {}",
                    attempt,
                    attempts,
                    str(exc)[:110],
                )
            else:
                if response.status_code == 200:
                    return response
                if response.status_code == 429 or response.status_code >= 500:
                    last = HimalayasError(
                        f"HTTP {response.status_code} from Himalayas"
                    )
                    logger.warning(
                        "Himalayas HTTP {} (attempt {}/{})",
                        response.status_code,
                        attempt,
                        attempts,
                    )
                else:
                    raise HimalayasPermanentError(
                        f"Himalayas returned HTTP {response.status_code} for {url}"
                    )

            if attempt < attempts:
                time.sleep(self.settings.retry_backoff_seconds * (2 ** (attempt - 1)))

        logger.error("Himalayas request failed after {} attempts: {}", attempts, last)
        return None

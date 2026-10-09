"""Fetches the raw job feed from Arbeitnow's public API.

This module's only responsibility is: make the HTTP request (with retries for
transient failures), confirm the response looks like a job feed, and hand back
raw dictionaries. It does not validate individual job fields -- that is
``parser.py``'s job. Keeping these separate means a network problem and a
data-quality problem show up as different, distinguishable errors, the same
boundary ``RemoteOKClient``/``RemotiveClient`` already establish.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_json,
)
from job_market_intel.common.retry import call_with_retry

from .config import ArbeitnowSettings
from .exceptions import ArbeitnowFetchError, ArbeitnowResponseError


class ArbeitnowClient:
    """Fetches the current Arbeitnow job listing feed."""

    def __init__(self, settings: ArbeitnowSettings | None = None) -> None:
        self._settings = settings or ArbeitnowSettings()

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch the current feed and return raw job dictionaries.

        The response is a JSON object with the postings under ``data`` and
        pagination metadata under ``links``/``meta``. Arbeitnow's API returns
        the whole active listing in one response, so there is no pagination to
        manage here.

        Raises:
            ArbeitnowFetchError: The API could not be reached after exhausting
                retries, or returned a permanent HTTP error.
            ArbeitnowResponseError: Valid JSON, but not shaped like a job feed.
        """
        logger.info("Fetching Arbeitnow job feed from {}", self._settings.api_url)
        try:
            payload = call_with_retry(
                fetch_json,
                self._settings.api_url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
            )
        except TransientHTTPError as exc:
            raise ArbeitnowFetchError(
                f"Could not reach Arbeitnow after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise ArbeitnowFetchError(f"Arbeitnow request failed permanently: {exc}") from exc

        if not isinstance(payload, dict):
            raise ArbeitnowResponseError(
                f"Expected a JSON object, got {type(payload).__name__}. "
                "The API's shape may have changed."
            )
        jobs = payload.get("data")
        if not isinstance(jobs, list):
            raise ArbeitnowResponseError(
                "Expected the response to contain a 'data' list. The API's shape may have changed."
            )

        records = [entry for entry in jobs if isinstance(entry, dict)]
        if not records:
            raise ArbeitnowResponseError(
                "Arbeitnow returned a response with zero recognizable job records. "
                "The API's shape may have changed, or this may be rate-limiting."
            )
        logger.info(
            "Fetched {} job records from Arbeitnow ({} non-job entries filtered).",
            len(records),
            len(jobs) - len(records),
        )
        return records

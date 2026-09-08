"""Fetches the raw job feed from Remotive's public API.

This module's only responsibility is: make the HTTP request (with retries
for transient failures), confirm the response looks like a job feed, and
hand back raw dictionaries. It does not validate individual job fields —
that is ``parser.py``'s job. Keeping these separate means a network
problem and a data-quality problem show up as different, distinguishable
errors, same boundary ``RemoteOKClient``/``WWRClient`` already establish.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_json
from job_market_intel.common.retry import call_with_retry

from .config import RemotiveSettings
from .exceptions import RemotiveFetchError, RemotiveResponseError


class RemotiveClient:
    """Fetches the current Remotive job listing feed."""

    def __init__(self, settings: RemotiveSettings | None = None) -> None:
        """Create a client.

        Args:
            settings: Configuration to use. If omitted, ``RemotiveSettings()``
                is constructed with its defaults (and any overrides present
                in the environment/``.env`` file), matching the project's
                existing configuration pattern.
        """
        self._settings = settings or RemotiveSettings()

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch the current Remotive job feed and return raw job dictionaries.

        Remotive's response shape is genuinely different from RemoteOK's:
        the top level is a dict (``{"job-count": N, "jobs": [...]}``), not
        a bare list, so this method's shape check is written for that,
        not adapted from RemoteOK's list check.

        Returns:
            A list of raw job dictionaries, in Remotive's own field
            naming, extracted from the response's ``jobs`` key.

        Raises:
            RemotiveFetchError: If the Remotive API could not be reached
                after exhausting all configured retry attempts, or if a
                permanent (non-retryable) HTTP error occurred (e.g.
                Remotive returned a 404 or a non-JSON body).
            RemotiveResponseError: If the response was valid JSON but was
                not shaped like a job feed at all (e.g. not a dict, or
                missing/malformed ``jobs``).
        """
        logger.info("Fetching Remotive job feed from {}", self._settings.api_url)

        try:
            raw_response = call_with_retry(
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
            raise RemotiveFetchError(
                f"Could not reach Remotive after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise RemotiveFetchError(f"Remotive request failed permanently: {exc}") from exc

        if not isinstance(raw_response, dict):
            raise RemotiveResponseError(
                f"Expected Remotive's response to be a JSON dict, got "
                f"{type(raw_response).__name__} instead. The API's shape may have changed."
            )

        jobs = raw_response.get("jobs")
        if not isinstance(jobs, list):
            raise RemotiveResponseError(
                "Expected Remotive's response to contain a 'jobs' list. "
                "The API's shape may have changed."
            )

        job_records = [entry for entry in jobs if isinstance(entry, dict)]
        skipped_non_dict_entries = len(jobs) - len(job_records)

        if not job_records:
            raise RemotiveResponseError(
                "Remotive returned a response with zero recognizable job records. "
                "The API's shape may have changed, or this may be an empty/rate-limited response."
            )

        logger.info(
            "Fetched {} job records from Remotive ({} non-job entries filtered out).",
            len(job_records),
            skipped_non_dict_entries,
        )
        return job_records

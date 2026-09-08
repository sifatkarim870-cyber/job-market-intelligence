"""Fetches the raw job feed from RemoteOK's public API.

This module's only responsibility is: make the HTTP request (with retries
for transient failures), confirm the response looks like a job list, and
hand back raw dictionaries. It does not validate individual job fields —
that is ``parser.py``'s job. Keeping these separate means a network problem
and a data-quality problem show up as different, distinguishable errors.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_json
from job_market_intel.common.retry import call_with_retry

from .config import RemoteOKSettings
from .exceptions import RemoteOKFetchError, RemoteOKResponseError


class RemoteOKClient:
    """Fetches the current RemoteOK job listing feed."""

    def __init__(self, settings: RemoteOKSettings | None = None) -> None:
        """Create a client.

        Args:
            settings: Configuration to use. If omitted, ``RemoteOKSettings()``
                is constructed with its defaults (and any overrides present
                in the environment/``.env`` file), matching the project's
                existing configuration pattern.
        """
        self._settings = settings or RemoteOKSettings()

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch the current RemoteOK job feed and return raw job dictionaries.

        RemoteOK's feed has a documented quirk: the first element of the
        returned JSON array is not a job posting at all — it is a
        legal/attribution notice object. Every genuine job record has an
        ``id`` field; the metadata entry does not. This method filters out
        any top-level entry missing an ``id``, so callers only ever see
        actual job records.

        Returns:
            A list of raw job dictionaries, in RemoteOK's own field
            naming, with the non-job metadata entry removed.

        Raises:
            RemoteOKFetchError: If the RemoteOK API could not be reached
                after exhausting all configured retry attempts, or if a
                permanent (non-retryable) HTTP error occurred (e.g. RemoteOK
                returned a 404 or a non-JSON body).
            RemoteOKResponseError: If the response was valid JSON but was
                not shaped like a job feed at all (e.g. not a list).
        """
        logger.info("Fetching RemoteOK job feed from {}", self._settings.api_url)

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
            raise RemoteOKFetchError(
                f"Could not reach RemoteOK after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise RemoteOKFetchError(f"RemoteOK request failed permanently: {exc}") from exc

        if not isinstance(raw_response, list):
            raise RemoteOKResponseError(
                f"Expected RemoteOK's response to be a JSON list, got "
                f"{type(raw_response).__name__} instead. The feed's shape may have changed."
            )

        job_records = [entry for entry in raw_response if isinstance(entry, dict) and "id" in entry]
        skipped_non_job_entries = len(raw_response) - len(job_records)

        if not job_records:
            raise RemoteOKResponseError(
                "RemoteOK returned a response with zero recognizable job records. "
                "The feed's shape may have changed, or this may be an empty/rate-limited response."
            )

        logger.info(
            "Fetched {} job records from RemoteOK ({} non-job entries filtered out).",
            len(job_records),
            skipped_non_job_entries,
        )
        return job_records

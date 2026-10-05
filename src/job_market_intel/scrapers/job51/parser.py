"""Validates raw 51job records into typed ``RawJob51Job`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run. For 51job the
expected skip cause is a structural oddity in an otherwise uniform feed
(missing ``jobId``/``jobName``/``jobHref``/``issueDateString``) — each
such record is rejected by ``RawJob51Job``'s validators and logged at
warning level with the item's own id, then the run continues.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawJob51Job


class Job51Parser:
    """Turns raw 51job API dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawJob51Job]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``Job51Client.fetch_raw_jobs()``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawJob51Job] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawJob51Job.from_api_entry(raw_job)
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("jobId", f"<no jobId, index {index}>")
                logger.warning(
                    "Skipping malformed 51job job record (jobId={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "51job parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

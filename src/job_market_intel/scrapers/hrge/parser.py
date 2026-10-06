"""Validates raw HR.ge records into typed ``RawHRGeJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawHRGeJob


class HRGeParser:
    """Turns raw HR.ge API dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawHRGeJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``HRGeClient.fetch_raw_jobs()``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawHRGeJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawHRGeJob.from_api_entry(raw_job)
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("announcementId", f"<no id, index {index}>")
                logger.warning(
                    "Skipping malformed HR.ge job record (id={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "HR.ge parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

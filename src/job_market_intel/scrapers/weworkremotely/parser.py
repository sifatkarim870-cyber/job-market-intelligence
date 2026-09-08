"""Validates raw We Work Remotely item dictionaries into typed RawWWRJob objects.

Mirrors ``scrapers/remoteok/parser.py`` exactly: one bad record must
never take down the rest of a batch. Every record is validated
independently; a record that fails validation (missing required field,
unsplittable title, etc.) is logged and skipped, not raised.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawWWRJob


class WWRParser:
    """Validates a batch of raw We Work Remotely job dictionaries."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawWWRJob]:
        """Validate each raw job dict into a ``RawWWRJob``, skipping malformed records.

        Args:
            raw_jobs: Raw dictionaries as returned by
                ``WWRClient.fetch_raw_jobs()``.

        Returns:
            The subset of ``raw_jobs`` that validated successfully,
            each wrapped as a ``RawWWRJob`` with ``raw_payload`` attached.
        """
        parsed_jobs: list[RawWWRJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawWWRJob.model_validate({**raw_job, "raw_payload": raw_job})
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("guid") or f"<no guid, index {index}>"
                logger.warning(
                    "Skipping malformed We Work Remotely job record (guid={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "We Work Remotely parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

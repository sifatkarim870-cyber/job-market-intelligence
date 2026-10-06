"""Validates raw Glints records into typed ``RawGlintsJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawGlintsJob


class GlintsParser:
    """Turns raw Glints page payloads into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawGlintsJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``GlintsClient.fetch_raw_jobs()``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawGlintsJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawGlintsJob.from_page_payload(
                    raw_job, original_url=raw_job.get("original_url", "")
                )
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("id", f"<no id, index {index}>")
                logger.warning(
                    "Skipping malformed Glints job record (id={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Glints parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

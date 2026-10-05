"""Validates raw Job.am records into typed ``RawJobAmJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run. For job.am the
common skip cause is a listed job whose detail page already 404s —
without that page there is no ``datePosted``, and
``RawJobAmJob._parse_posted_at`` rejects the record (see the model's
module docstring).
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawJobAmJob


class JobAmParser:
    """Turns raw Job.am API dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawJobAmJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``JobAmClient.fetch_raw_jobs()``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawJobAmJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawJobAmJob.from_api_entry(raw_job)
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("Id", f"<no Id, index {index}>")
                logger.warning(
                    "Skipping malformed Job.am job record (Id={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Job.am parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

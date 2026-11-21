"""Validates raw BLMIS records into typed ``RawBlmisJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawBlmisJob


class BlmisParser:
    """Turns raw BLMIS vacancy records into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawBlmisJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``BlmisClient.fetch_raw_jobs()`` --
                ``{"id": application_no, "record": vacancy dict,
                "oversea": bool, "url": public detail page URL}``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawBlmisJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawBlmisJob.from_payload(
                    raw_job.get("record"),
                    original_url=raw_job.get("url", ""),
                    is_oversea=bool(raw_job.get("oversea", False)),
                )
            except (ValidationError, ValueError) as exc:
                # ValidationError: required identity fields empty.
                # ValueError: record absent/not an object -- equally
                # malformed as far as this record is concerned.
                skipped_count += 1
                identifier = raw_job.get("id", f"<index {index}>")
                logger.warning(
                    "Skipping malformed BLMIS job record ({}): {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "BLMIS parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

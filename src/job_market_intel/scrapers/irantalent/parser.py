"""Validates raw Irantalent records into typed ``RawIrantalentJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawIrantalentJob


class IrantalentParser:
    """Turns raw Irantalent search rows into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawIrantalentJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``IrantalentClient.fetch_raw_jobs()``
                — ``{"url": constructed /{locale}/job/{slug}/{id}``,
                "payload": search data dict}``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawIrantalentJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawIrantalentJob.from_payload(
                    raw_job.get("payload"),
                    original_url=raw_job.get("url", ""),
                )
            except (ValidationError, ValueError) as exc:
                # ValidationError: required identity fields empty.
                # ValueError: payload absent/not an object — equally
                # malformed as far as this record is concerned.
                skipped_count += 1
                identifier = raw_job.get("url", f"<index {index}>")
                logger.warning(
                    "Skipping malformed Irantalent job record ({}): {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Irantalent parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

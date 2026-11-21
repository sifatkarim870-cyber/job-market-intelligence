"""Validates raw Bdjobs records into typed ``RawBdjobsJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawBdjobsJob


class BdjobsParser:
    """Turns raw Bdjobs search+detail records into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawBdjobsJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``BdjobsClient.fetch_raw_jobs()``
                -- ``{"id": Jobid, "listing": search row dict, "detail":
                detail dict or None, "url": public detail page URL}``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawBdjobsJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawBdjobsJob.from_payload(
                    raw_job.get("listing"),
                    raw_job.get("detail"),
                    original_url=raw_job.get("url", ""),
                )
            except (ValidationError, ValueError) as exc:
                # ValidationError: required identity fields empty.
                # ValueError: listing absent/not an object -- equally
                # malformed as far as this record is concerned.
                skipped_count += 1
                identifier = raw_job.get("id", f"<index {index}>")
                logger.warning(
                    "Skipping malformed Bdjobs job record ({}): {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Bdjobs parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

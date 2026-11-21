"""Validates raw Zangia records into typed ``RawZangiaJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawZangiaJob


class ZangiaParser:
    """Turns raw Zangia listing+detail records into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawZangiaJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``ZangiaClient.fetch_raw_jobs()`` --
                ``{"url": public job URL, "listing": listing row dict,
                "detail": detail dict or None}``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawZangiaJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawZangiaJob.from_payload(
                    raw_job.get("listing"),
                    raw_job.get("detail"),
                    original_url=raw_job.get("url", ""),
                )
            except (ValidationError, ValueError) as exc:
                # ValidationError: required identity fields empty.
                # ValueError: listing absent/not an object -- equally
                # malformed as far as this record is concerned.
                skipped_count += 1
                identifier = raw_job.get("url", f"<index {index}>")
                logger.warning(
                    "Skipping malformed Zangia job record ({}): {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Zangia parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

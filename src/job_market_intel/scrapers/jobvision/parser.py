"""Validates raw Jobvision records into typed ``RawJobvisionJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawJobvisionJob


class JobvisionParser:
    """Turns raw Jobvision API payloads into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawJobvisionJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``JobvisionClient.fetch_raw_jobs()``
                — ``{"url": canonical sitemap URL, "payload": API data}``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawJobvisionJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawJobvisionJob.from_payload(
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
                    "Skipping malformed Jobvision job record ({}): {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Jobvision parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

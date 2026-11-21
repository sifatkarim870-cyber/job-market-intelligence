"""Validates raw BongThom records into typed ``RawBongthomJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawBongthomJob


class BongthomParser:
    """Turns raw BongThom discovery+detail records into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawBongthomJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw entries from ``BongthomClient.fetch_raw_jobs()``
                -- ``{"id": id, "listing": discovery row dict, "embed":
                get_embed dict or None, "workplace": rendered workplace dict,
                "url": public detail page URL}``.

        Returns:
            The successfully validated jobs; never raises on a bad record.
        """
        parsed_jobs: list[RawBongthomJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawBongthomJob.from_payload(
                    raw_job.get("listing"),
                    raw_job.get("embed"),
                    raw_job.get("workplace"),
                    original_url=raw_job.get("url", ""),
                )
            except (ValidationError, ValueError) as exc:
                # ValidationError: required identity fields empty.
                # ValueError: listing absent/not an object -- equally
                # malformed as far as this record is concerned.
                skipped_count += 1
                identifier = raw_job.get("id", f"<index {index}>")
                logger.warning(
                    "Skipping malformed BongThom job record ({}): {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "BongThom parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

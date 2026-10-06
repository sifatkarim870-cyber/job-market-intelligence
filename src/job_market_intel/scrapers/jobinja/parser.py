"""Validates raw Jobinja records into typed ``RawJobinjaJob`` objects.

Same role and skip-don't-crash philosophy as the other sources' parsers:
one malformed record must never take down an entire run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawJobinjaJob


class JobinjaParser:
    """Turns raw Jobinja page payloads into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawJobinjaJob]:
        """Validate every raw job dictionary, skipping malformed ones.

        Args:
            raw_jobs: Raw ``{"url": …, "html": …}`` entries from
                ``JobinjaClient.fetch_raw_jobs()``.

        Returns:
            The successfully validated jobs; never raises on a bad
            record. A page without a JSON-LD ``JobPosting`` (or with one
            missing identifier/title/company) counts as skipped and is
            surfaced through the batch validator's skip-rate check.
        """
        parsed_jobs: list[RawJobinjaJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            url = raw_job.get("url", "")
            try:
                validated_job = RawJobinjaJob.from_page_html(
                    raw_job.get("html", ""), original_url=url
                )
            except (ValidationError, ValueError) as exc:
                skipped_count += 1
                logger.warning(
                    "Skipping malformed Jobinja job record (url={}, index {}): {}",
                    url or "<no url>",
                    index,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Jobinja parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

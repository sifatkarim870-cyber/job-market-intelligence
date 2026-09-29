"""Validates raw Reed records into typed ``RawReedJob`` objects.

Mirrors ``scrapers/remoteok/parser.py``'s/``scrapers/remotive/parser.py``'s
role and skip-don't-crash philosophy — see those modules' docstrings for
the full rationale. Only structural difference: each input here is
already a ``{"search": ..., "details": ...}`` pair (assembled by
``pipeline.py`` — see that module's docstring for why the merge decision
happens there, not here), not a single flat record.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawReedJob


class ReedParser:
    """Turns combined Reed search+details records into validated ``RawReedJob`` objects."""

    def parse_jobs(self, combined_records: list[dict]) -> list[RawReedJob]:
        """Validate every combined record, skipping and logging any that are malformed.

        Args:
            combined_records: Each entry is a dict with keys ``"search"``
                (required, one raw Search result) and ``"details"``
                (that job's raw Details response — see
                ``pipeline.py``'s module docstring for why, in this
                pipeline's normal operation, a job only reaches this
                parser once its Details fetch has already succeeded).

        Returns:
            A list of successfully validated ``RawReedJob`` objects. May
            be shorter than ``combined_records`` if any were skipped.
        """
        parsed_jobs: list[RawReedJob] = []
        skipped_count = 0

        for index, combined in enumerate(combined_records):
            search = combined.get("search") or {}
            details = combined.get("details")
            try:
                validated_job = RawReedJob.from_combined(search, details)
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = search.get("jobId", f"<no jobId, index {index}>")
                logger.warning(
                    "Skipping malformed Reed job record (jobId={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Reed parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(combined_records),
        )
        return parsed_jobs

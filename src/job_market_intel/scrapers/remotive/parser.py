"""Validates raw Remotive JSON records into typed ``RawRemotiveJob`` objects.

Mirrors ``scrapers/remoteok/parser.py``'s role and skip-don't-crash
philosophy exactly — see that module's docstring for the full rationale.
A single malformed job record must never take down an entire scrape run;
Remotive returns hundreds of records per request, and one corrupted field
should not cost the other 99%+ that are still valuable.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawRemotiveJob


class RemotiveParser:
    """Turns a list of raw Remotive job dictionaries into validated ``RawRemotiveJob`` objects."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawRemotiveJob]:
        """Validate every raw job dictionary, skipping and logging any that are malformed.

        Args:
            raw_jobs: Raw job dictionaries as returned by
                ``RemotiveClient.fetch_raw_jobs()`` (Remotive's own field
                names, already extracted from the response's ``jobs`` key).

        Returns:
            A list of successfully validated ``RawRemotiveJob`` objects.
            May be shorter than ``raw_jobs`` if any records were skipped.
        """
        parsed_jobs: list[RawRemotiveJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                # raw_payload is populated explicitly here (rather than via
                # a field alias) because it isn't one of Remotive's own
                # fields — it's a deliberate copy of the entire original
                # record, kept for auditability, same principle every
                # other source's parser follows.
                validated_job = RawRemotiveJob.model_validate({**raw_job, "raw_payload": raw_job})
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("id", f"<no id, index {index}>")
                logger.warning(
                    "Skipping malformed Remotive job record (id={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "Remotive parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

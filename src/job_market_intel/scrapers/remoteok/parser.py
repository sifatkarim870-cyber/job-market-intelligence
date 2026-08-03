"""Validates raw RemoteOK JSON records into typed ``RawRemoteOKJob`` objects.

This is the layer most likely to need attention over time — if RemoteOK
adds, renames, or removes a field, this is where you'll see it, either as
Pydantic validation errors in the logs or as unexpectedly empty optional
fields. Keeping this isolated from ``client.py`` (which only knows how to
fetch the feed) means a RemoteOK field change never requires touching the
networking code, and vice versa.

Design decision — skip, don't crash: a single malformed job record must
never take down an entire scrape run. RemoteOK returns thousands of
records per request; if one has a corrupted field, the other 99.9% are
still valuable and should still be collected. Malformed records are logged
with enough detail to investigate later, then skipped.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawRemoteOKJob


class RemoteOKParser:
    """Turns a list of raw RemoteOK job dictionaries into validated ``RawRemoteOKJob`` objects."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawRemoteOKJob]:
        """Validate every raw job dictionary, skipping and logging any that are malformed.

        Args:
            raw_jobs: Raw job dictionaries as returned by
                ``RemoteOKClient.fetch_raw_jobs()`` (RemoteOK's own field
                names, already stripped of the feed's non-job metadata
                entry).

        Returns:
            A list of successfully validated ``RawRemoteOKJob`` objects.
            May be shorter than ``raw_jobs`` if any records were skipped.
        """
        parsed_jobs: list[RawRemoteOKJob] = []
        skipped_count = 0

        for index, raw_job in enumerate(raw_jobs):
            try:
                # raw_payload is populated explicitly here (rather than via
                # a field alias) because it isn't one of RemoteOK's own
                # fields — it's a deliberate copy of the entire original
                # record, kept for auditability per the platform's
                # "never discard the original source data" principle.
                validated_job = RawRemoteOKJob.model_validate({**raw_job, "raw_payload": raw_job})
            except ValidationError as exc:
                skipped_count += 1
                job_identifier = raw_job.get("id", f"<no id, index {index}>")
                logger.warning(
                    "Skipping malformed RemoteOK job record (id={}): {}",
                    job_identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "RemoteOK parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            skipped_count,
            len(raw_jobs),
        )
        return parsed_jobs

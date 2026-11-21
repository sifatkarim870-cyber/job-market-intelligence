"""Validates raw ANPE Burkina Faso posts into typed ``RawAnpeBfJob`` objects."""

from __future__ import annotations

from loguru import logger

from .models import RawAnpeBfJob


class AnpeBfParser:
    """Turns raw WordPress post dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawAnpeBfJob]:
        """Validate every raw post, skipping malformed ones.

        Args:
            raw_jobs: Raw post objects from ``AnpeBfClient.fetch_raw_jobs()``.

        Returns:
            The validated models that parsed, in input order.

        Raises:
            AnpeBfResponseError-like ValueError: Only when zero records parse,
                which means the endpoint's shape changed.
        """
        parsed_jobs: list[RawAnpeBfJob] = []

        for index, raw_job in enumerate(raw_jobs):
            try:
                validated_job = RawAnpeBfJob.from_payload(raw_job)
            except Exception as exc:  # noqa: BLE001 - per-record skip by design
                identifier = raw_job.get("id") if isinstance(raw_job, dict) else f"<index {index}>"
                logger.warning(
                    "Skipping malformed ANPE Burkina Faso record {}: {}",
                    identifier,
                    exc,
                )
                continue
            parsed_jobs.append(validated_job)

        logger.info(
            "ANPE Burkina Faso parsing complete: {} valid, {} skipped, {} total records.",
            len(parsed_jobs),
            len(raw_jobs) - len(parsed_jobs),
            len(raw_jobs),
        )
        return parsed_jobs

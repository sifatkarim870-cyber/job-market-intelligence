"""Validates raw Kariyer.net records into ``RawKariyerNetJob`` models.

Skip, don't crash: one malformed record must not end the run. ``source_job_id``
and ``title`` are the only required fields -- without an identity there is
nothing to de-duplicate on, and without a title there is nothing to analyse.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from .models import RawKariyerNetJob


class KariyerNetParser:
    """Turns raw gateway dictionaries into validated models."""

    def parse_jobs(self, raw_records: list[dict]) -> list[RawKariyerNetJob]:
        parsed: list[RawKariyerNetJob] = []
        skipped = 0

        for index, raw in enumerate(raw_records):
            if not isinstance(raw, dict):
                skipped += 1
                logger.warning("Kariyer.net record {} is not an object; skipping", index)
                continue
            if not raw.get("source_job_id") or not str(raw.get("source_job_id")).strip():
                skipped += 1
                logger.warning("Kariyer.net record {} has no jobId; skipping", index)
                continue
            try:
                parsed.append(
                    RawKariyerNetJob.model_validate({**raw, "raw": raw.get("raw") or raw})
                )
            except ValidationError as exc:
                skipped += 1
                logger.warning(
                    "Kariyer.net record {} failed validation ({}); skipping",
                    index,
                    str(exc).splitlines()[0][:160],
                )

        if skipped:
            logger.info("Kariyer.net parser skipped {} of {} records", skipped, len(raw_records))
        return parsed

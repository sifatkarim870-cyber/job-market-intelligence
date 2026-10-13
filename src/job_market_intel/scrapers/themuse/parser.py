"""Validates raw The Muse records into ``RawThemuseJob`` models.

Also applies the age cutoff. The API offers no date filter and is not
time-ordered -- sampling the first three pages on 2026-10-12 returned
publication dates from 2025-01-17 to 2026-10-03 -- so a walk of this feed
without a cutoff mostly imports long-expired vacancies.
"""

from __future__ import annotations

import datetime as dt

from loguru import logger
from pydantic import ValidationError

from job_market_intel.scrapers.themuse.models import RawThemuseJob


class ThemuseParser:
    """Turns raw API dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawThemuseJob]:
        parsed: list[RawThemuseJob] = []
        skipped = 0

        for index, raw in enumerate(raw_jobs):
            if not isinstance(raw, dict):
                skipped += 1
                logger.warning("The Muse record {} is not an object; skipping", index)
                continue
            try:
                parsed.append(RawThemuseJob.model_validate({**raw, "raw_payload": raw}))
            except ValidationError as exc:
                skipped += 1
                logger.warning(
                    "The Muse record {} failed validation ({}); skipping",
                    index,
                    str(exc).splitlines()[0][:160],
                )

        if skipped:
            logger.info("The Muse parser skipped {} of {} records", skipped, len(raw_jobs))
        return parsed

    @staticmethod
    def drop_stale(jobs: list[RawThemuseJob], max_age_days: int) -> list[RawThemuseJob]:
        """Keep postings published within ``max_age_days``.

        A record with no parseable publication date is KEPT rather than
        dropped: an unknown date is not evidence of staleness, and this feed is
        new enough that discarding everything undated would be the wrong
        default.
        """
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=max_age_days)
        kept: list[RawThemuseJob] = []
        undated = 0

        for job in jobs:
            posted = job.posting_date
            if posted is None:
                undated += 1
                kept.append(job)
            elif posted >= cutoff:
                kept.append(job)

        logger.info(
            "The Muse age filter ({} days) kept {} of {} postings ({} undated, retained)",
            max_age_days,
            len(kept),
            len(jobs),
            undated,
        )
        return kept

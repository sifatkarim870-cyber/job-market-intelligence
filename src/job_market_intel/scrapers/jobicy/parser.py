"""Validates raw Jobicy records into ``RawJobicyJob`` models.

Skip, don't crash: one malformed record must not end a run.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from job_market_intel.scrapers.jobicy.models import RawJobicyJob


class JobicyParser:
    """Turns raw API dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawJobicyJob]:
        parsed: list[RawJobicyJob] = []
        skipped = 0

        for index, raw in enumerate(raw_jobs):
            if not isinstance(raw, dict):
                skipped += 1
                logger.warning("Jobicy record {} is not an object; skipping", index)
                continue
            try:
                parsed.append(RawJobicyJob.model_validate({**raw, "raw_payload": raw}))
            except ValidationError as exc:
                skipped += 1
                logger.warning(
                    "Jobicy record {} failed validation ({}); skipping",
                    index,
                    str(exc).splitlines()[0][:160],
                )

        if skipped:
            logger.info("Jobicy parser skipped {} of {} records", skipped, len(raw_jobs))
        return parsed

    @staticmethod
    def filter_focus(
        jobs: list[RawJobicyJob], focus_industries: list[str]
    ) -> list[RawJobicyJob]:
        """Keep postings whose ``jobIndustry`` matches any focus term.

        Substring matching, case-insensitive: the feed uses 'Software
        Development' and 'Data Science & Analytics', so an exact set match
        would drop the compound labels that carry most of the technical rows.
        An empty filter keeps everything.
        """
        if not focus_industries:
            return jobs
        wanted = [t.strip().lower() for t in focus_industries if t.strip()]

        kept: list[RawJobicyJob] = []
        for job in jobs:
            haystack = " ".join(job.jobIndustry).lower()
            if any(term in haystack for term in wanted):
                kept.append(job)

        logger.info(
            "Jobicy industry filter kept {} of {} postings",
            len(kept),
            len(jobs),
        )
        return kept

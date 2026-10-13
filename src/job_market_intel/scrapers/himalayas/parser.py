"""Validates raw Himalayas records into ``RawHimalayasJob`` models.

Skip, don't crash. A single malformed record must not end a run: the feed is
small enough that one bad row is a visible percentage of the batch, and the
alternative is a red workflow that stored nothing.

``guid`` and ``title`` are the only required fields, because without them there
is no identity to deduplicate on and no text to analyse.
"""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from job_market_intel.scrapers.himalayas.models import RawHimalayasJob


class HimalayasParser:
    """Turns raw API dictionaries into validated models."""

    def parse_jobs(self, raw_jobs: list[dict]) -> list[RawHimalayasJob]:
        parsed: list[RawHimalayasJob] = []
        skipped = 0

        for index, raw in enumerate(raw_jobs):
            if not isinstance(raw, dict):
                skipped += 1
                logger.warning("Himalayas record {} is not an object; skipping", index)
                continue
            try:
                parsed.append(RawHimalayasJob.model_validate({**raw, "raw_payload": raw}))
            except ValidationError as exc:
                skipped += 1
                logger.warning(
                    "Himalayas record {} failed validation ({}); skipping",
                    index,
                    str(exc).splitlines()[0][:160],
                )

        if skipped:
            logger.info("Himalayas parser skipped {} of {} records", skipped, len(raw_jobs))
        return parsed

    @staticmethod
    def filter_focus(
        jobs: list[RawHimalayasJob], focus_categories: list[str]
    ) -> list[RawHimalayasJob]:
        """Keep only postings in one of ``focus_categories``.

        Matching is case-insensitive and substring-based on purpose: the feed
        uses "Information Technology" and "Data Science" but also "Engineering
        and Data Science", and an exact-set match would drop the compound ones.
        An empty filter disables the filter entirely.
        """
        if not focus_categories:
            return jobs
        wanted = [c.strip().lower() for c in focus_categories if c.strip()]

        kept: list[RawHimalayasJob] = []
        for job in jobs:
            haystack = " ".join([*job.parentCategories, *job.categories, job.title or ""]).lower()
            if any(term in haystack for term in wanted):
                kept.append(job)

        logger.info(
            "Himalayas focus filter kept {} of {} postings (categories: {})",
            len(kept),
            len(jobs),
            ", ".join(wanted),
        )
        return kept

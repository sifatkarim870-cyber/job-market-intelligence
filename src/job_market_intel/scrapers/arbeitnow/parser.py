"""Parses raw Arbeitnow dictionaries into validated ``RawArbeitnowJob`` models.

Split from the client so a network problem and a payload problem stay
distinguishable, matching the boundary every other scraper in this project
draws.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.arbeitnow.models import RawArbeitnowJob

from .exceptions import ArbeitnowParseError


class ArbeitnowParser:
    """Turns raw Arbeitnow dicts into ``RawArbeitnowJob`` objects."""

    def parse_job(self, record: dict) -> RawArbeitnowJob:
        """Parse one posting.

        Raises:
            ArbeitnowParseError: The record has no usable slug or title. Both
                are load-bearing -- the slug is the natural key that makes
                re-runs idempotent, and a blank title is not a job posting.
        """
        try:
            return RawArbeitnowJob.model_validate(record)
        except Exception as exc:  # noqa: BLE001 - pydantic raises several types
            raise ArbeitnowParseError(
                f"Could not parse Arbeitnow posting "
                f"(slug={record.get('slug')!r}, title={record.get('title')!r}): {exc}"
            ) from exc

    def parse_jobs(self, records: list[dict]) -> tuple[list[RawArbeitnowJob], list[str]]:
        """Parse a batch, dropping and reporting individual bad records.

        A single malformed posting must not cost the feed's worth of good ones,
        so failures are collected rather than raised.
        """
        parsed: list[RawArbeitnowJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(self.parse_job(record))
            except ArbeitnowParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Arbeitnow records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues

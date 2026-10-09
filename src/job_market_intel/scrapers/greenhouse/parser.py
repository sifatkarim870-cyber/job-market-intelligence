"""Parses raw Greenhouse dictionaries into validated ``RawGreenhouseJob`` models.

Split from the client so a network problem and a payload problem stay
distinguishable, matching the boundary every other scraper in this project
draws.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.greenhouse.models import RawGreenhouseJob

from .exceptions import GreenhouseParseError


class GreenhouseParser:
    """Turns raw Greenhouse dicts into ``RawGreenhouseJob`` objects."""

    def parse_job(self, record: dict) -> RawGreenhouseJob:
        """Parse one posting.

        Raises:
            GreenhouseParseError: The record has no usable id or title. Both
                are load-bearing -- the id is the natural key that makes
                re-runs idempotent, and a blank title is not a job posting --
                so a record missing either is dropped rather than stored.
        """
        try:
            return RawGreenhouseJob.model_validate(record)
        except Exception as exc:  # noqa: BLE001 - pydantic raises several types
            raise GreenhouseParseError(
                f"Could not parse Greenhouse posting "
                f"(id={record.get('id')!r}, title={record.get('title')!r}): {exc}"
            ) from exc

    def parse_jobs(self, records: list[dict]) -> tuple[list[RawGreenhouseJob], list[str]]:
        """Parse a batch, dropping and reporting individual bad records.

        A single malformed posting must not cost us an entire board's worth of
        good ones, so failures are collected rather than raised.
        """
        parsed: list[RawGreenhouseJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(self.parse_job(record))
            except GreenhouseParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Greenhouse records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues

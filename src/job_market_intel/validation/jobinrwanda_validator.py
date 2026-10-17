"""Batch validation for the Job in Rwanda scraper.

``posted_date`` is deliberately **not** in the census: the board publishes no
posting date at all, so a check there would be a permanent 100% failure that
says nothing about the parser. ``closing_date`` is checked instead, and it too
is expected to be frequently absent -- four of six inspected pages state no
deadline -- so its presence is informative rather than a gate.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobinrwanda.models import RawJobInRwandaJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 200,
    "url": lambda job: not job.url or not job.url.strip(),
    "closing_date": lambda job: job.closing_date is None,
}


class JobInRwandaValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``JOBINRWANDA_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="JOBINRWANDA_VALIDATION_", extra="ignore")

    #: The homepage carries 199 postings, so anything below that means the link
    #: pattern stopped matching rather than that the board shrank.
    min_expected_jobs: int = 100
    max_skip_rate: float = 0.25


class JobInRwandaBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: JobInRwandaValidationSettings | None = None) -> None:
        self._settings = settings or JobInRwandaValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobInRwandaJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Job in Rwanda",
        )

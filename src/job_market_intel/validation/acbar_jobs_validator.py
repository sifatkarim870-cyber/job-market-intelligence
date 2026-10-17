"""Batch validation for the ACBAR jobs scraper.

``salary`` is **not** in the census: every measured posting states a prose value
("As Per Organization", "Negotiable") rather than a figure, so a check there would
be a permanent 100% failure saying nothing about the parser. The verbatim string
is kept in ``raw_payload["salary_text"]`` instead.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.acbar_jobs.models import RawAcbarJobsJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 200,
    "location": lambda job: not job.location,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    "employment_type": lambda job: not job.employment_type,
}


class AcbarJobsValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``ACBAR_JOBS_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="ACBAR_JOBS_VALIDATION_", extra="ignore")

    #: A listing page yields 20 postings, so below that means the link pattern
    #: stopped matching rather than that the board shrank.
    min_expected_jobs: int = 20
    max_skip_rate: float = 0.25


class AcbarJobsBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: AcbarJobsValidationSettings | None = None) -> None:
        self._settings = settings or AcbarJobsValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawAcbarJobsJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="ACBAR Jobs",
        )

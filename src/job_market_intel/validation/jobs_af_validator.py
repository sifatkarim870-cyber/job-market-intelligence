"""Batch validation for the Jobs.af scraper.

``salary`` is **not** in the census: the measured posting carries no
``baseSalary``, so a check there would be a permanent 100% failure saying nothing
about the parser.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobs_af.models import RawJobsAfJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location and not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class JobsAfValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``JOBS_AF_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="JOBS_AF_VALIDATION_", extra="ignore")

    #: The homepage carries 12 postings. The floor is set below that so a couple
    #: of expired postings cannot fail the run, while a broken link pattern --
    #: which returns zero -- still does.
    min_expected_jobs: int = 8
    max_skip_rate: float = 0.25


class JobsAfBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: JobsAfValidationSettings | None = None) -> None:
        self._settings = settings or JobsAfValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobsAfJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Jobs.af",
        )

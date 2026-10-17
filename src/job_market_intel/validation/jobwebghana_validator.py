"""Batch validation for the Jobweb Ghana scraper.

``salary`` is in the census but expected to read **1.0 missing** -- every
measured posting carries only the site-wide placeholder, and the cleaner rejects
it. That is the correct outcome, not a regression, and the number is what proves
it rather than leaving the decision invisible.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobwebghana.models import RawJobwebGhanaJob
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
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
}


class JobwebGhanaValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``JOBWEBGHANA_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="JOBWEBGHANA_VALIDATION_", extra="ignore")

    #: Page 1 carries 22 postings and later pages 13, so a floor of 15 catches a
    #: broken link pattern without failing a genuinely short tail.
    min_expected_jobs: int = 15
    max_skip_rate: float = 0.25


class JobwebGhanaBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: JobwebGhanaValidationSettings | None = None) -> None:
        self._settings = settings or JobwebGhanaValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobwebGhanaJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Jobweb Ghana",
        )

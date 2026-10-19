"""Batch validation for the Jobs.ge scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobsge.models import RawJobsGeJob
from job_market_intel.validation.common import validate_batch

#: ``location`` and ``salary`` are deliberately absent.
#:
#: Jobs.ge publishes **neither** in a structured field -- Tbilisi appears in
#: the ad body and pay appears in prose -- so requiring either would fail
#: every row and make the report meaningless. ``country`` is the honest field
#: and it is always present.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 200,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "country": lambda job: not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class JobsGeValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBSGE_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class JobsGeBatchValidator:
    def __init__(self, settings: JobsGeValidationSettings | None = None) -> None:
        self._settings = settings or JobsGeValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobsGeJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Jobs.ge",
        )

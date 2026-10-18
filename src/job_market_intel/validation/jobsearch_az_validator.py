"""Batch validation for the JobSearch.az scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobsearch_az.models import RawJobSearchAzJob
from job_market_intel.validation.common import validate_batch

#: ``location`` is deliberately absent from these checks. The detail page names
#: cities only in prose, so every parsed posting has ``location is None`` --
#: checking it would fail 30 of 30 records and make the report meaningless.
#: ``country`` is the honest field, and it is always present.
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


class JobSearchAzValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBSEARCH_AZ_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class JobSearchAzBatchValidator:
    def __init__(self, settings: JobSearchAzValidationSettings | None = None) -> None:
        self._settings = settings or JobSearchAzValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobSearchAzJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="JobSearch.az",
        )

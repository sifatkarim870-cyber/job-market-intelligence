"""Batch validation for the Corporate Staffing Services (Kenya) scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.corporatestaffing_ke.models import RawCorporateStaffingJob
from job_market_intel.validation.common import validate_batch

_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 200,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    "employment_type": lambda job: not job.employment_type,
}


class CorporateStaffingValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORPORATE_STAFFING_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 20
    max_skip_rate: float = 0.25


class CorporateStaffingBatchValidator:
    def __init__(self, settings: CorporateStaffingValidationSettings | None = None) -> None:
        self._settings = settings or CorporateStaffingValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawCorporateStaffingJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Corporate Staffing",
        )

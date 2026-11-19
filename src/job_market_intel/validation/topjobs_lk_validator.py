"""Batch validation for the TopJobs (Sri Lanka) scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.topjobs_lk.models import RawTopJobsLkJob
from job_market_intel.validation.common import validate_batch

#: ``description`` is checked for reporting only -- it is absent on ~95% of
#: this board's ads because the body is an image, which is a property of the
#: board, not a parser failure. It is therefore not a pass/fail signal.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "company": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location,
    "description": lambda job: not job.description,
    "closing_date": lambda job: job.closing_date is None,
    "employment_type": lambda job: not job.employment_type,
    "url": lambda job: not job.url or not job.url.strip(),
}


class TopJobsLkValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOPJOBS_LK_VALIDATION_", extra="ignore")

    #: The open board held 4,583 postings on 2026-11-20. A run that parses
    #: fewer than 50 is degraded even at the smallest useful cap.
    min_expected_jobs: int = 50
    max_skip_rate: float = 0.2


class TopJobsLkBatchValidator:
    def __init__(self, settings: TopJobsLkValidationSettings | None = None) -> None:
        self._settings = settings or TopJobsLkValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawTopJobsLkJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="TopJobs (Sri Lanka)",
        )

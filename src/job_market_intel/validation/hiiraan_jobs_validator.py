"""Batch validation for the Hiiraan jobs scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.hiiraan_jobs.models import RawHiiraanJobsJob
from job_market_intel.validation.common import validate_batch

_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 200,
    "location": lambda job: not job.location,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    "employment_type": lambda job: not job.employment_type,
}


class HiiraanJobsValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIIRAAN_JOBS_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 4
    max_skip_rate: float = 0.25


class HiiraanJobsBatchValidator:
    def __init__(self, settings: HiiraanJobsValidationSettings | None = None) -> None:
        self._settings = settings or HiiraanJobsValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawHiiraanJobsJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Hiiraan Jobs",
        )

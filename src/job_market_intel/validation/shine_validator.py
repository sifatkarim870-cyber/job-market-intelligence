"""Batch validation for the Shine.com scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.shine.models import RawShineJob
from job_market_intel.validation.common import validate_batch

#: ``location`` is optional because some postings read "All India" which
#: resolves to country-only -- honest, not a parser gap.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: job.description is None,  # informational only
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "country": lambda job: not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class ShineValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHINE_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class ShineBatchValidator:
    def __init__(self, settings: ShineValidationSettings | None = None) -> None:
        self._settings = settings or ShineValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawShineJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Shine.com",
        )

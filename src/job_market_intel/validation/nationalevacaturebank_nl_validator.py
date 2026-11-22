"""Batch validation for the Nationale Vacaturebank (Netherlands) scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.nationalevacaturebank_nl.models import (
    RawNationaleVacaturebankNlJob,
)
from job_market_intel.validation.common import validate_batch

#: ``company_name`` and ``location`` are absent on some ads, so they are
#: watched but not treated as failures -- only the fields every genuine ad
#: must have are strict enough to matter.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description_html or len(job.description_html) < 40,
    "company_name": lambda job: not job.company_name or job.company_name == "Unknown employer",
    "location_text": lambda job: not job.location_text,
    "posted_date": lambda job: job.posted_date is None,
    "job_url": lambda job: not job.job_url or not job.job_url.strip(),
}


class NationaleVacaturebankNlValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NATIONALE_VACATUREBANK_NL_VALIDATION_", extra="ignore"
    )

    #: A run fetches up to 60 ads; anything below 10 means a category window
    #: returned almost nothing, which is a markup/throttle signal rather than a
    #: quiet board.
    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class NationaleVacaturebankNlBatchValidator:
    def __init__(self, settings: NationaleVacaturebankNlValidationSettings | None = None) -> None:
        self._settings = settings or NationaleVacaturebankNlValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawNationaleVacaturebankNlJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Nationale Vacaturebank",
        )

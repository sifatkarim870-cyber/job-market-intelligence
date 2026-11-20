"""Batch validation for the L'Express Petites Annonces (Mauritius) scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.lexpress_mu.models import RawLexpressMuJob
from job_market_intel.validation.common import validate_batch

#: ``company_name`` and ``location`` are frequently absent on a classifieds
#: board, so they are watched but not treated as failures -- only the fields
#: every genuine ad must have are strict enough to matter.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 40,
    "company_name": lambda job: not job.company_name or job.company_name == "Unknown employer",
    "location": lambda job: not job.location,
    "posted_date": lambda job: job.posted_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class LexpressMuValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEXPRESS_MU_VALIDATION_", extra="ignore")

    #: The category held 126+ ads live; a run that returns fewer than 10 has
    #: almost certainly hit a markup change rather than a quiet board.
    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class LexpressMuBatchValidator:
    def __init__(self, settings: LexpressMuValidationSettings | None = None) -> None:
        self._settings = settings or LexpressMuValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawLexpressMuJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="L'Express Petites Annonces",
        )

"""Batch-level validation for a single HR.ge scrape run.

Thin wrapper around ``validation.common.validate_batch`` with HR.ge's
own thresholds and missing-field checks, same pattern as the other
sources' validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.hrge.models import RawHRGeJob

_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "contract_type_raw": lambda job: not job.contract_type_raw,
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "tags": lambda job: len(job.tags) == 0,
    "posting_date": lambda job: job.posting_date is None,
}


class HRGeValidationSettings(BaseSettings):
    """Configurable thresholds for HR.ge batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="HRGE_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to 40 pages x 100 = 4,000 jobs (the live
    # site reports ~3,596 active vacancies), so a healthy run is always
    # in the hundreds. 100 still passes a deliberately capped single-page
    # run while flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=100, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class HRGeBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: HRGeValidationSettings | None = None) -> None:
        self._settings = settings or HRGeValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawHRGeJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
        )

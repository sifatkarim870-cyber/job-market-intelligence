"""Batch-level validation for a single BongThom scrape run.

Thin wrapper around ``validation.common.validate_batch`` with BongThom's own
thresholds and missing-field checks, same pattern as the other sources'
validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.bongthom_com.models import RawBongthomJob

_MISSING_FIELD_CHECKS = {
    "job_title": lambda job: not job.job_title.strip(),
    "company_name": lambda job: not job.company_name,
    "location_text": lambda job: not job.location_text,
    "description": lambda job: not (job.description_htmls or job.duty_texts or job.benefit_texts),
    "posting_date": lambda job: job.posting_date is None,
    "employment_type": lambda job: not job.employment_type_raw,
    "salary_disclosure": lambda job: not job.salary_text_raw,
}


class BongthomValidationSettings(BaseSettings):
    """Configurable thresholds for BongThom batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="BONGTHOM_COM_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The whole board held 278 jobs at scoping, so a healthy run is in the
    # hundreds. 10 clears a deliberately tiny local run while flagging
    # anything emptier as suspicious.
    min_expected_jobs: int = Field(default=10, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class BongthomBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: BongthomValidationSettings | None = None) -> None:
        self._settings = settings or BongthomValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawBongthomJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="BongThom",
        )

"""Batch-level validation for a single ANPE Burkina Faso scrape run.

Thin wrapper around ``validation.common.validate_batch`` with this
source's own thresholds and missing-field checks, same pattern as the
other validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.anpe_bf.models import RawAnpeBfJob

_MISSING_FIELD_CHECKS = {
    "description_html": lambda job: not (job.description_html or job.excerpt_html),
    "posting_date": lambda job: job.posting_date is None,
    "job_title": lambda job: not job.job_title.strip(),
}


class AnpeBfValidationSettings(BaseSettings):
    """Configurable thresholds for ANPE Burkina Faso batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="ANPE_BF_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The whole offers category was 97 posts at scoping. A run reads every
    # page, so 30 is a low floor that still flags a truncated/empty swipe
    # while tolerating the category shrinking between runs.
    min_expected_jobs: int = Field(default=30, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class AnpeBfBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: AnpeBfValidationSettings | None = None) -> None:
        self._settings = settings or AnpeBfValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawAnpeBfJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="ANPE Burkina Faso",
        )

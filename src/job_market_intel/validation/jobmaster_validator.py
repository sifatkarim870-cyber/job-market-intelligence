"""Batch-level validation for a single JobMaster scrape run.

Thin wrapper around ``validation.common.validate_batch`` with
JobMaster's own thresholds and missing-field checks, same pattern as
the other sources' validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobmaster.models import RawJobmasterJob

_MISSING_FIELD_CHECKS = {
    "location_text": lambda job: not job.location_text,
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "category_raws": lambda job: not job.category_raws,
    "work_type_label": lambda job: not job.work_type_label,
    "salary_disclosure": lambda job: job.salary_text is None,
}


class JobmasterValidationSettings(BaseSettings):
    """Configurable thresholds for JobMaster batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="JOBMASTER_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # A healthy CI run fetches up to 400 rows, so a passing run is
    # usually well in the hundreds; 50 keeps deliberately small tails
    # legal while flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=50, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class JobmasterBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: JobmasterValidationSettings | None = None) -> None:
        self._settings = settings or JobmasterValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawJobmasterJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="JobMaster",
        )

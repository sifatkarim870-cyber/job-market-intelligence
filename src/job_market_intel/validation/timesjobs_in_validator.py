"""Batch-level validation for a single TimesJobs scrape run.

Thin wrapper around ``validation.common.validate_batch`` with TimesJobs'
own thresholds and missing-field checks, same pattern as the other
sources' validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.timesjobs_in.models import RawTimesjobsJob

_MISSING_FIELD_CHECKS = {
    "location_text": lambda job: not job.location_text,
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "skills_tags": lambda job: not job.skills_raw and not job.function_raws,
    "employment_type": lambda job: not job.employment_type_raw,
    "salary_disclosure": lambda job: job.salary_min_raw is None and job.salary_max_raw is None,
}


class TimesjobsValidationSettings(BaseSettings):
    """Configurable thresholds for TimesJobs batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="TIMESJOBS_IN_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to 200 rows (TIMESJOBS_IN_MAX_JOBS_PER_RUN),
    # so a healthy CI run is in the hundreds; 50 still passes a deliberately
    # small run while flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=50, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class TimesjobsBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: TimesjobsValidationSettings | None = None) -> None:
        self._settings = settings or TimesjobsValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawTimesjobsJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="TimesJobs",
        )

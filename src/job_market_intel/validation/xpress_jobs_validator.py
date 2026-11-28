"""Batch-level validation for a single XpressJobs scrape run.

Thin wrapper around ``validation.common.validate_batch`` with XpressJobs'
own thresholds and missing-field checks, same pattern as the other
sources' validators. ``skills`` is deliberately not checked: the board
publishes no skill list at all (see ``cleaning/xpress_jobs_cleaner.py``),
so a 100%-missing skills rate would be a property of the board, not a
parser failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.xpress_jobs.models import RawXpressJob

_MISSING_FIELD_CHECKS = {
    "location_text": lambda job: not job.location_text,
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "company_name": lambda job: not job.company_name,
    "employment_type": lambda job: not job.employment_type_raw,
    "salary_disclosure": lambda job: job.salary_min_raw is None and job.salary_max_raw is None,
}


class XpressJobsValidationSettings(BaseSettings):
    """Configurable thresholds for XpressJobs batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="XPRESS_JOBS_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to 200 rows (XPRESS_JOBS_MAX_JOBS_PER_RUN),
    # so a healthy CI run is in the hundreds; 50 still passes a deliberately
    # small run while flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=50, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class XpressJobsBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: XpressJobsValidationSettings | None = None) -> None:
        self._settings = settings or XpressJobsValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawXpressJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="XpressJobs",
        )

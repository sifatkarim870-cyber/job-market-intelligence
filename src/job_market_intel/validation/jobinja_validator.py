"""Batch-level validation for a single Jobinja scrape run.

Thin wrapper around ``validation.common.validate_batch`` with Jobinja's
own thresholds and missing-field checks, same pattern as the other
sources' validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobinja.models import RawJobinjaJob

_MISSING_FIELD_CHECKS = {
    "location_spans": lambda job: not job.location_spans,
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "skills_spans": lambda job: len(job.skills_spans) == 0,
    "employment_type_raw": lambda job: not job.employment_type_raw,
    "salary_disclosure": lambda job: not job.salary_text_spans,
}


class JobinjaValidationSettings(BaseSettings):
    """Configurable thresholds for Jobinja batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="JOBINGJA_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to 400 unique jobs
    # (JOBINGJA_MAX_JOBS_PER_RUN), so a healthy CI run is always in the
    # hundreds; 100 still passes a deliberately small run (e.g. a
    # start-page-offset backfill chunk) while flagging anything emptier
    # as suspicious.
    min_expected_jobs: int = Field(default=100, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class JobinjaBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: JobinjaValidationSettings | None = None) -> None:
        self._settings = settings or JobinjaValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawJobinjaJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Jobinja",
        )

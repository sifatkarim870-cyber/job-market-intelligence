"""Batch-level validation for a single Jobvision scrape run.

Thin wrapper around ``validation.common.validate_batch`` with Jobvision's
own thresholds and missing-field checks, same pattern as the other
sources' validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobvision.models import RawJobvisionJob

_MISSING_FIELD_CHECKS = {
    "location_parts": lambda job: not job.location_parts,
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "skills_tags": lambda job: not (
        job.category_raws
        or job.software_names
        or job.language_names
        or job.industry_raws
        or job.skills_raws
    ),
    "work_type": lambda job: not job.work_type_en and not job.is_internship,
    "salary_disclosure": lambda job: (
        job.salary_min_raw is None and job.salary_max_raw is None
    ),
}


class JobvisionValidationSettings(BaseSettings):
    """Configurable thresholds for Jobvision batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="JOBVISION_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to 400 unique jobs
    # (JOBVISION_MAX_JOBS_PER_RUN), so a healthy CI run is always in
    # the hundreds; 100 still passes a deliberately small run (e.g. a
    # local backfill chunk) while flagging anything emptier as
    # suspicious.
    min_expected_jobs: int = Field(default=100, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class JobvisionBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: JobvisionValidationSettings | None = None) -> None:
        self._settings = settings or JobvisionValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list["RawJobvisionJob"],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Jobvision",
        )

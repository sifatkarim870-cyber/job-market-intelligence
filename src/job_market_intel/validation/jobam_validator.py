"""Batch-level validation for a single Job.am scrape run.

Thin wrapper around ``validation.common.validate_batch`` with Job.am's
own thresholds and missing-field checks, same pattern as the other
sources' validators.

One Job.am-specific calibration note (measured 2026-10-05 over the
first 100 listed jobs): 6 of them pointed at detail pages that already
404, so ~6% of raw records are expected to be skipped for lack of a
posting date. That fits inside the default 10% ``max_skip_rate`` — but
if job.am's dead-listing backlog grows past that, raising
``JOBAM_VALIDATION_MAX_SKIP_RATE`` is the honest fix (the listing is
genuinely gone), not code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobam.models import RawJobAmJob

_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "employment_type_raw": lambda job: not job.employment_type_raw,
    "closing_date": lambda job: job.closing_date is None,
}


class JobAmValidationSettings(BaseSettings):
    """Configurable thresholds for Job.am batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="JOBAM_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run processes up to max_jobs_per_run = 100 jobs; flag
    # runs that come back suspiciously small.
    min_expected_jobs: int = Field(default=10, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class JobAmBatchValidator:
    """Evaluates whether a completed Job.am fetch+parse cycle is healthy."""

    def __init__(self, settings: JobAmValidationSettings | None = None) -> None:
        self._settings = settings or JobAmValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawJobAmJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Job.am",
        )

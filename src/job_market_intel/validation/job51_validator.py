"""Batch-level validation for a single 51job scrape run.

Thin wrapper around ``validation.common.validate_batch`` with 51job's
own thresholds and missing-field checks, same pattern as the other
sources' validators.

One 51job-specific calibration note (measured 2026-10-05 over 300 items
of the general feed): every item carried a parseable posting date, a
description, an employment type, and a salary — so the default 10%
``max_skip_rate`` and the informational missing-field rates both start
from a clean baseline. ``salary_min`` is included as a *signal*, not an
expectation: if the board ever stops disclosing pay, that rate climbing
is exactly what the missing-field report should show (it never fails a
run on its own — see ``validation/common.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.job51.models import RawJob51Job

_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "employment_type_raw": lambda job: not job.employment_type_raw,
    "salary_min": lambda job: job.salary_min is None,
}


class Job51ValidationSettings(BaseSettings):
    """Configurable thresholds for 51job batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="JOB51_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run processes up to max_jobs_per_run = 300 jobs; flag
    # runs that come back suspiciously small.
    min_expected_jobs: int = Field(default=10, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class Job51BatchValidator:
    """Evaluates whether a completed 51job fetch+parse cycle is healthy."""

    def __init__(self, settings: Job51ValidationSettings | None = None) -> None:
        self._settings = settings or Job51ValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawJob51Job],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="51job",
        )

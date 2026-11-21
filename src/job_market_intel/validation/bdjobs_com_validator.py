"""Batch-level validation for a single Bdjobs scrape run.

Thin wrapper around ``validation.common.validate_batch`` with Bdjobs' own
thresholds and missing-field checks, same pattern as the other sources'
validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.bdjobs_com.models import RawBdjobsJob

_MISSING_FIELD_CHECKS = {
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "location_text": lambda job: not job.location_text,
    "posting_date": lambda job: job.posting_date is None,
    "skills_raw": lambda job: not job.skills_raw,
    "employment_type_raw": lambda job: not job.employment_type_raw,
    "salary_disclosure": lambda job: job.salary_min_raw is None and job.salary_max_raw is None,
}


class BdjobsValidationSettings(BaseSettings):
    """Configurable thresholds for Bdjobs batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="BDJOBS_COM_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to BDJOBS_COM_MAX_JOBS_PER_RUN rows (default
    # 200) while the whole board was ~5,747 at scoping, so a healthy run is
    # in the dozens-to-hundreds. 20 still clears a deliberately tiny local
    # run while flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=20, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class BdjobsBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: BdjobsValidationSettings | None = None) -> None:
        self._settings = settings or BdjobsValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawBdjobsJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Bdjobs",
        )

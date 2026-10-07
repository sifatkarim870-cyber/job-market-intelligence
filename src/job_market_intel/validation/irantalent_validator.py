"""Batch-level validation for a single Irantalent scrape run.

Thin wrapper around ``validation.common.validate_batch`` with Irantalent's
own thresholds and missing-field checks, same pattern as the other
sources' validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.irantalent.models import RawIrantalentJob

_MISSING_FIELD_CHECKS = {
    "location_text": lambda job: not job.location_text,
    "description_html": lambda job: not job.description_html or not job.description_html.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "skills_tags": lambda job: not (job.category_raws or job.industry_raws),
    "work_type": lambda job: not job.work_type_en,
    "salary_disclosure": lambda job: job.salary_min_raw is None and job.salary_max_raw is None,
}


class IrantalentValidationSettings(BaseSettings):
    """Configurable thresholds for Irantalent batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="IRANTALENT_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # One capped run fetches up to 400 rows (IRANTALENT_MAX_JOBS_PER_RUN),
    # so a healthy CI run is always in the hundreds; 100 still passes a
    # deliberately small run (e.g. a backfill tail — the whole live
    # corpus is only ~1,872 rows, so late chunks are thinner) while
    # flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=100, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class IrantalentBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: IrantalentValidationSettings | None = None) -> None:
        self._settings = settings or IrantalentValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawIrantalentJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Irantalent",
        )

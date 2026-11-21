"""Batch-level validation for a single BLMIS scrape run.

Thin wrapper around ``validation.common.validate_batch`` with BLMIS' own
thresholds and missing-field checks, same pattern as the other sources'
validators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.blmis_bt.models import RawBlmisJob

_MISSING_FIELD_CHECKS = {
    "job_title": lambda job: not job.job_title.strip(),
    "company_name": lambda job: not job.company_name,
    "location_text": lambda job: not job.location_text,
    "description": lambda job: (
        not (job.description_raw or job.qualification_raw or job.remarks_raw)
    ),
    "posting_date": lambda job: job.posting_date is None,
    "employment_type": lambda job: not job.employment_type_raw,
    "salary_disclosure": lambda job: job.salary_min_raw is None,
}


class BlmisValidationSettings(BaseSettings):
    """Configurable thresholds for BLMIS batch validation."""

    model_config = SettingsConfigDict(
        env_prefix="BLMIS_BT_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The whole board held 442 vacancies at scoping, so a healthy run is in
    # the hundreds. 20 still clears a deliberately tiny local run while
    # flagging anything emptier as suspicious.
    min_expected_jobs: int = Field(default=20, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class BlmisBatchValidator:
    """Evaluates whether a completed fetch+parse cycle is healthy."""

    def __init__(self, settings: BlmisValidationSettings | None = None) -> None:
        self._settings = settings or BlmisValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawBlmisJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="BLMIS",
        )

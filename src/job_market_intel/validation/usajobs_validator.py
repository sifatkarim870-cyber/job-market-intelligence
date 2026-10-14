"""Batch validation for the USAJOBS scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

One check is specific to USAJOBS and is treated as required rather than
informational. The federal board publishes a ``PositionStartDate`` and an
``ApplicationCloseDate``, so a posting with neither is not merely sparse -- it
means the envelope changed or the page fetch silently failed, and the corpus
would fill with undatable rows that cannot be aged or expired. Same reasoning
as the Job Bank validator's ``posted_date`` check.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.usajobs.models import RawUSAJobsJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "organization_name": lambda job: not job.organization_name or not job.organization_name.strip(),
    "location_display": lambda job: not job.location_display or not job.location_display.strip(),
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class USAJobsValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``USAJOBS_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="USAJOBS_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    #: The default walk is one 50-result page per keyword, and a keyword whose
    #: matches are all outside the first page can legitimately return nothing
    #: new. A skip rate above this means the parse is dropping records, not
    #: that a keyword was quiet.
    max_skip_rate: float = 0.25


class USAJobsBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: USAJobsValidationSettings | None = None) -> None:
        self._settings = settings or USAJobsValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawUSAJobsJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="USAJOBS",
        )

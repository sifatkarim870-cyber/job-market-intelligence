"""Batch validation for the Arbeitnow scraper.

Follows the same shape as every other source's validator: a batch-level health
report (never raises), plus a missing-field census specific to what Arbeitnow
actually promises.

Arbeitnow is unusually complete for a free board: it returns the full
description, a location, job types and tags on most postings. The required
checks are only the things every posting must have -- a slug (the natural key,
without which the row cannot be deduplicated) and a title.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.arbeitnow.models import RawArbeitnowJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING from a
#: parsed posting. These are callables, not booleans: ``validate_batch``
#: invokes each one per record.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or not job.description.strip(),
    "url": lambda job: not job.url or not job.url.strip(),
    "location": lambda job: not job.location,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
}


class ArbeitnowValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``ARBEITNOW_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="ARBEITNOW_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 50
    max_skip_rate: float = 0.25


class ArbeitnowBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: ArbeitnowValidationSettings | None = None) -> None:
        self._settings = settings or ArbeitnowValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawArbeitnowJob],
    ):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Arbeitnow",
        )

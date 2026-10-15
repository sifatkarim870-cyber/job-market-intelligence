"""Batch validation for the Built In scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

Built In needs one check the others do not, because its detail pages nest the
``JobPosting`` node inside an ``@graph`` document. A parser that reads only the
top level of the JSON-LD finds no postings at all and reports an empty batch --
which is indistinguishable from a quiet board. So this validator requires a
description, and the pipeline's own ``parsed_count == 0`` on a non-empty
discovery is the louder signal.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.builtin.models import RawBuiltInJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "locations": lambda job: not job.locations and not job.location_countries,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class BuiltInValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``BUILTIN_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="BUILTIN_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    #: A listing page yields 20-27 distinct links, so a high skip rate means the
    #: parser is dropping records rather than that a facet page was quiet.
    max_skip_rate: float = 0.25


class BuiltInBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: BuiltInValidationSettings | None = None) -> None:
        self._settings = settings or BuiltInValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawBuiltInJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Built In",
        )

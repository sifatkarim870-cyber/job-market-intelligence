"""Batch validation for the Wellfound scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

Wellfound needs one check the other sources do not. Discovery only works
through ``/location/...`` and ``/role/...`` pages, and ``/jobs`` renders a
pager it then ignores -- so a silent markup change would still produce *some*
links while reaching a fraction of the board. ``posted_date`` is therefore
required, not merely censused: every posting measured carried a ``datePosted``,
and a batch without them means the JSON-LD is no longer what this parser
expects.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.wellfound.models import RawWellfoundJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "locations": lambda job: not job.locations and not job.location_countries,
    "posted_date": lambda job: job.posted_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class WellfoundValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``WELLFOUND_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="WELLFOUND_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    #: A listing page yields ~45-58 distinct links, so a high skip rate means the
    #: parser is dropping records rather than that a listing was quiet.
    max_skip_rate: float = 0.25


class WellfoundBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: WellfoundValidationSettings | None = None) -> None:
        self._settings = settings or WellfoundValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawWellfoundJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Wellfound",
        )

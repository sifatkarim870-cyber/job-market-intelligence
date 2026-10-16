"""Batch validation for the Net-Empregos scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

The one judgement call is the description floor. Every other validator in this
project uses 100 characters, and on boards with 2-6k descriptions that is a
reasonable proxy for "the parser found nothing". It is not here: measured
descriptions run 3400+ characters, so a 100-character floor is comfortable.

``baseSalary`` is not checked at all: Net-Empregos publishes none, so a salary
check would be a permanent 100% failure that says nothing.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.net_empregos.models import RawNetEmpregosJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location and not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    "employment_type": lambda job: not job.employment_type,
}


class NetEmpregosValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``NET_EMPREGOS_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="NET_EMPREGOS_VALIDATION_", extra="ignore")

    #: A listing page yields 18 distinct postings, so anything below 18 means
    #: discovery broke early rather than that the board was quiet.
    min_expected_jobs: int = 18
    #: One page per path and a first-hit-wins walk, so a high skip rate means
    #: the parser is dropping records.
    max_skip_rate: float = 0.25


class NetEmpregosBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: NetEmpregosValidationSettings | None = None) -> None:
        self._settings = settings or NetEmpregosValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawNetEmpregosJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Net-Empregos",
        )

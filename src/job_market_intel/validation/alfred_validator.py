"""Batch validation for the Alfred scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

The description floor is the one judgement call. Every other validator in this
project uses 100 characters, and on boards with 2-6k descriptions that is a
reasonable proxy for "the parser found nothing". It is not here: measured
descriptions run **17 to 2656** characters, because a handful of sitemap
entries are general-application pages that describe the employer rather than a
vacancy. A 100-character floor would cull real postings and, worse, would
encourage someone to turn the check off.

The floor here is therefore 10 characters -- below the measured minimum, so it
asks only "is there a description at all". ``jobLocation`` is likewise absent on
3 of 10 real postings, so it is counted and never required.

``baseSalary`` is not checked at all: Alfred publishes none (0 of 10 measured),
so a salary check would be a permanent 100% failure that says nothing.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.alfred.models import RawAlfredJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    # See the module docstring: the measured minimum is 17 characters.
    "description": lambda job: not job.description or len(job.description) < 10,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    # Absent on 3 of 10 real postings, so counted and never required.
    "location": lambda job: not job.location and not job.country,
    "posted_date": lambda job: job.posted_date is None,
    # validThrough is nullable in the source itself.
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    "employment_type": lambda job: not job.employment_type,
}


class AlfredValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``ALFRED_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="ALFRED_VALIDATION_", extra="ignore")

    #: A floor on **surviving vacancies**, not on sitemap entries.
    #:
    #: This was originally 25, set from the sitemap's 624 URLs before the
    #: general-application pages were understood. Those are roughly two thirds
    #: of the sitemap -- measured 20 of the first 30 entries, and 19 of the
    #: first 28 stored rows -- so a 30-posting run legitimately yields about 10
    #: real vacancies, and the batch was failing its own health check for being
    #: correct.
    #:
    #: The check exists to catch a feed that has stopped parsing, so the floor
    #: only has to sit below the expected yield and above zero. A full
    #: ``ALFRED_MAX_JOBS_PER_RUN`` of 150 yields roughly 50 vacancies; 8 catches
    #: a broken feed without firing on a deliberately small run.
    min_expected_jobs: int = 8
    #: One URL per posting and first-hit-wins, so a high skip rate means the
    #: parser is dropping records.
    max_skip_rate: float = 0.25


class AlfredBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: AlfredValidationSettings | None = None) -> None:
        self._settings = settings or AlfredValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawAlfredJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Alfred",
        )

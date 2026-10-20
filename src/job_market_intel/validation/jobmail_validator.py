"""Batch validation for the JobMail scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobmail.models import RawJobMailJob
from job_market_intel.validation.common import validate_batch

#: ``salary`` is deliberately absent. Measured over 10 live postings, only 2
#: carried a numeric ``baseSalary`` and the listing card publishes a figure on
#: roughly a third of them; the rest publish the words "Market Related" or
#: nothing. Requiring a figure would fail most of the board and make the
#: report meaningless.
#:
#: The description threshold is 200, measured: the JobPosting ``description``
#: ran 1,432-5,510 characters on the postings sampled.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 200,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "country": lambda job: not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "location": lambda job: not job.location,
    "url": lambda job: not job.url or not job.url.strip(),
}


class JobMailValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBMAIL_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class JobMailBatchValidator:
    def __init__(self, settings: JobMailValidationSettings | None = None) -> None:
        self._settings = settings or JobMailValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobMailJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="JobMail",
        )

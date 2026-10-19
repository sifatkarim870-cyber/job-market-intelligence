"""Batch validation for the JobsIreland.ie scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobsireland.models import RawJobsIrelandJob
from job_market_intel.validation.common import validate_batch

#: ``salary`` is deliberately absent. The detail page carries a euro icon
#: (``alt="Image for Euro"``) beside the *label* of a link to a programme-wide
#: rates page -- "Community Employment Programme Rates" -- and carries no
#: figure. Requiring a salary would fail every row and make the report
#: meaningless.
#:
#: The description threshold is 400, measured rather than copied: over 14 live
#: postings ``.job-description`` ran 645-1,268 characters (median 800) and
#: 0/14 fell under 400. The bare ``<pre>`` bound to the Description field was
#: the tempting wrong choice -- it ran 87-818 characters and 8/14 sat under 200.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 400,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "country": lambda job: not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "location": lambda job: not job.location_reduced,
    "url": lambda job: not job.url or not job.url.strip(),
}


class JobsIrelandValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBSIRELAND_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.25


class JobsIrelandBatchValidator:
    def __init__(self, settings: JobsIrelandValidationSettings | None = None) -> None:
        self._settings = settings or JobsIrelandValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobsIrelandJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="JobsIreland.ie",
        )

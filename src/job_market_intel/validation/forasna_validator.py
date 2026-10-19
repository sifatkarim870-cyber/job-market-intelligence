"""Batch validation for the Forasna scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.forasna.models import RawForasnaJob
from job_market_intel.validation.common import validate_batch

#: ``salary`` is deliberately absent. 32% of postings carry a figure
#: (measured over 60 live postings: 19 with a baseSalary, 41 without), so
#: requiring one would fail two thirds of the board and make the report
#: meaningless.
#:
#: The description threshold is 100, measured: the JSON-LD carries a
#: description on 44 of 60 sampled postings, and the ones that do are far
#: longer than 100 characters (the shortest sampled was 620). 27% of
#: postings have no body at all -- the employer left it empty and the page
#: shows only a structured requirements block, which is not a description.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "country": lambda job: not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "location": lambda job: not job.location,
    "url": lambda job: not job.url or not job.url.strip(),
}


class ForasnaValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORASNA_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.40


class ForasnaBatchValidator:
    def __init__(self, settings: ForasnaValidationSettings | None = None) -> None:
        self._settings = settings or ForasnaValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawForasnaJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Forasna",
        )

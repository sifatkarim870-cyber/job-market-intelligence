"""Batch validation for the HTML scraper framework."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.html_scraper.models import RawHtmlScraperJob
from job_market_intel.validation.common import validate_batch

_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: job.description is None,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "country": lambda job: not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class HtmlScraperValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HTML_SCRAPER_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 5
    max_skip_rate: float = 0.50


class HtmlScraperBatchValidator:
    def __init__(self, settings: HtmlScraperValidationSettings | None = None) -> None:
        self._settings = settings or HtmlScraperValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawHtmlScraperJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="HTML scraper",
        )

"""Batch validation for the Revolico (Cuba) scraper."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.revolico_cu.models import RawRevolicoCuJob
from job_market_intel.validation.common import validate_batch

#: ``company_name`` is *always* "Unknown employer" on this board (there is no
#: employer field at all), so it is watched but never a failure -- only the
#: fields every genuine ad must have are strict enough to matter.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 40,
    "company_name": lambda job: not job.company_name or job.company_name == "Unknown employer",
    "location": lambda job: not job.location,
    "posted_date": lambda job: job.posted_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class RevolicoCuValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REVOLICO_CU_VALIDATION_", extra="ignore")

    #: The employers' board held hundreds of pages (~100 ads each) live; a run
    #: that returns fewer than 20 has almost certainly hit a markup change
    #: rather than a quiet board.
    min_expected_jobs: int = 20
    max_skip_rate: float = 0.25


class RevolicoCuBatchValidator:
    def __init__(self, settings: RevolicoCuValidationSettings | None = None) -> None:
        self._settings = settings or RevolicoCuValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawRevolicoCuJob]):
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Revolico (Cuba)",
        )

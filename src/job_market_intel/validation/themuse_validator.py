"""Batch health checks for The Muse feed."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.themuse.models import RawThemuseJob
from job_market_intel.validation.common import validate_batch

#: Field -> predicate that is True when the field is MISSING from a posting.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "id": lambda job: not job.id or not str(job.id).strip(),
    "name": lambda job: not job.name or not job.name.strip(),
    "contents": lambda job: not job.contents or not job.contents.strip(),
    "company": lambda job: not job.company or not job.company.get("name"),
}


class ThemuseValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``THEMUSE_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="THEMUSE_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    max_skip_rate: float = 0.5


class ThemuseBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: ThemuseValidationSettings | None = None) -> None:
        self.settings = settings or ThemuseValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawThemuseJob],
    ) -> Any:
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self.settings.min_expected_jobs,
            max_skip_rate=self.settings.max_skip_rate,
            source_label="The Muse",
        )

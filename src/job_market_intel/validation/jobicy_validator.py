"""Batch health checks for the Jobicy feed."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobicy.models import RawJobicyJob
from job_market_intel.validation.common import validate_batch

#: Field -> predicate that is True when the field is MISSING from a posting.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "id": lambda job: not job.id or not str(job.id).strip(),
    "jobTitle": lambda job: not job.jobTitle or not job.jobTitle.strip(),
    "jobDescription": lambda job: not job.jobDescription or not job.jobDescription.strip(),
    "companyName": lambda job: not job.companyName or not job.companyName.strip(),
    # jobGeo is often absent on a remote feed; that is not a parse failure and
    # the cleaner resolves it to a remote placeholder.
}


class JobicyValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``JOBICY_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="JOBICY_VALIDATION_", extra="ignore")

    #: The whole feed is roughly 200 records, so a healthy batch is well under
    #: the numbers other validators use. Only a collapse is a fault.
    min_expected_jobs: int = 10
    max_skip_rate: float = 0.5


class JobicyBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: JobicyValidationSettings | None = None) -> None:
        self.settings = settings or JobicyValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawJobicyJob],
    ) -> Any:
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self.settings.min_expected_jobs,
            max_skip_rate=self.settings.max_skip_rate,
            source_label="Jobicy",
        )

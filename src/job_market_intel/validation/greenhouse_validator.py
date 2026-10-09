"""Batch validation for the Greenhouse scraper.

Follows the same shape as every other source's validator: a batch-level health
report (never raises), plus a missing-field census that is specific to what
Greenhouse actually promises.

Greenhouse is unusually complete compared with the job boards already in this
project. There is no salary field, so salary is deliberately absent from the
required checks -- flagging it would train operators to ignore the report.
What Greenhouse DOES reliably provide is the title, the apply URL and the
description HTML, and a posting missing any of those is genuinely broken.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.greenhouse.models import RawGreenhouseJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING from a
#: parsed posting. These are callables, not booleans: ``validate_batch``
#: invokes each one per record. The boolean form this file originally used
#: raises "'bool' object is not callable" on the first record.
#:
#: Deliberately small -- only what Greenhouse reliably supplies. There is no
#: salary entry, because flagging a field the source never publishes would
#: train operators to ignore the report.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "title": lambda job: not job.title or not job.title.strip(),
    "absolute_url": lambda job: not job.absolute_url or not job.absolute_url.strip(),
    "content": lambda job: not job.content or not job.content.strip(),
    "location": lambda job: not job.location_name,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
}


class GreenhouseValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``GREENHOUSE_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="GREENHOUSE_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 50
    max_skip_rate: float = 0.25


class GreenhouseBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: GreenhouseValidationSettings | None = None) -> None:
        self._settings = settings or GreenhouseValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawGreenhouseJob],
    ):
        """Produce a health report for one batch. Never raises.

        Args:
            raw_jobs: Raw dicts straight from ``GreenhouseClient.fetch_all``.
            parsed_jobs: The parser's output for those same dicts.
        """
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Greenhouse",
        )

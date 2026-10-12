"""Batch health checks for the Himalayas feed.

Separate from the parser on purpose. The parser asks "is this record
well-formed?"; this asks "is this BATCH healthy?" -- a feed can return
perfectly valid records that are all the same job, or a 40% drop rate that
silently empties the corpus. Both need to be visible without reading logs.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.himalayas.models import RawHimalayasJob
from job_market_intel.validation.common import validate_batch

#: Field -> predicate that is True when the field is MISSING from a posting.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "guid": lambda job: not job.guid or not job.guid.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or not job.description.strip(),
    "company_name": lambda job: not job.companyName or not job.companyName.strip(),
    # An empty location list is legitimate ("open to anyone"), so it is not a
    # missing-field failure here. It is resolved to "Worldwide / remote" by the
    # cleaner instead.
    "location": lambda job: not job.locationRestrictions,
}


class HimalayasValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``HIMALAYAS_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="HIMALAYAS_VALIDATION_", extra="ignore")

    #: The feed is a remote aggregator, not a national board, so a small batch
    #: is normal. Only a batch that has collapsed to near-nothing is a fault.
    min_expected_jobs: int = 10
    max_skip_rate: float = 0.5


class HimalayasBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: HimalayasValidationSettings | None = None) -> None:
        self.settings = settings or HimalayasValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawHimalayasJob],
    ) -> Any:
        """Return a report with ``passed``, ``skipped_rate`` and ``issues``."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self.settings.min_expected_jobs,
            max_skip_rate=self.settings.max_skip_rate,
            source_label="Himalayas",
        )

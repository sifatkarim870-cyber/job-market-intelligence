"""Batch health checks for the Kariyer.net feed.

Separate from the parser on purpose: the parser asks "is this record
well-formed?"; this asks "is this BATCH healthy?" -- a run that fetches a
plausible number of ads but loses most of them to a shape change needs to be
visible without reading logs.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.kariyer_net.models import RawKariyerNetJob
from job_market_intel.validation.common import validate_batch

#: Field -> predicate that is True when the field is MISSING from a posting.
#: These are informational rates, not pass/fail gates.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description_html and not job.description_text,
    "company_name": lambda job: (
        not job.company_name or job.company_name.strip().lower() in {"", "unknown employer"}
    ),
    "location": lambda job: not job.location_text or not job.location_text.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "url": lambda job: not job.job_url or not job.job_url.strip(),
}


class KariyerNetValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``KARIYER_NET_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="KARIYER_NET_VALIDATION_", extra="ignore")

    #: A 60-detail run is the target; anything under a handful means the gateway
    #: changed or throttled this client rather than the board being empty.
    min_expected_jobs: int = 5
    max_skip_rate: float = 0.5


class KariyerNetBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: KariyerNetValidationSettings | None = None) -> None:
        self.settings = settings or KariyerNetValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawKariyerNetJob],
    ) -> Any:
        """Return a report with ``passed``, ``skip_rate`` and ``issues``."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self.settings.min_expected_jobs,
            max_skip_rate=self.settings.max_skip_rate,
            source_label="Kariyer.net",
        )

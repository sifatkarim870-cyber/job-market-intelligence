"""Batch validation for the Job Bank Canada scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

Job Bank needs one check the other sources do not. Its pages are fed by
aggregators (Talent.com, ZipRecruiter and others post into it), and an
aggregator mirror can go stale or be stripped at any time -- the corpus would
then fill with rows that look fine and describe a posting that ended months
ago. So ``posted_date`` is a required field here, not an optional census
statistic: a batch with no dates at all is a signal, not just a gap.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.jobbank.models import RawJobBankJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "employer": lambda job: not job.employer or not job.employer.strip(),
    "posted_date": lambda job: job.posted_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
}


class JobBankValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``JOBBANK_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="JOBBANK_VALIDATION_", extra="ignore")

    min_expected_jobs: int = 10
    #: The default walk is one page across however many terms are configured;
    #: 25 is half a page of results, so a quarter of that as a failure
    #: threshold keeps a genuinely empty term from reddening every run.
    max_skip_rate: float = 0.25


class JobBankBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: JobBankValidationSettings | None = None) -> None:
        self._settings = settings or JobBankValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawJobBankJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Job Bank Canada",
        )

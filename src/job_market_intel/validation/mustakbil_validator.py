"""Batch validation for the Mustakbil scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

Two Mustakbil-specific points:

* **Descriptions are HTML in the structured field.** Every measured posting
  carries markup (``<b>``, ``<ul>``, ``<li>``) inside ``description``, and runs
  2-4k characters after stripping. The floor is therefore comfortable at 100.

* **There is no ``skills`` field here**, unlike Apna. Nothing is counted for it,
  because counting an absent-by-design field would put a permanent 0 in the
  census and make the number meaningless for the fields that do matter.

Note again that ``missing_field_checks`` produces a census and does not gate
``passed``: ``validate_batch`` only fails on record counts, skip rate and
duplicate ids. The census is where a per-field regression becomes visible.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.mustakbil.models import RawMustakbilJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location and not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    # Counted, never required: measured coverage is well under half.
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
    # Counted, never required: measured on a minority of postings.
    "experience": lambda job: job.months_of_experience is None,
}


class MustakbilValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``MUSTAKBIL_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="MUSTAKBIL_VALIDATION_", extra="ignore")

    #: The nine listing paths yield 123 distinct ids; anything under 25 means
    #: discovery broke early rather than that the board was quiet.
    min_expected_jobs: int = 25
    #: One page per path and a first-hit-wins walk, so a high skip rate means
    #: the parser is dropping records.
    max_skip_rate: float = 0.25


class MustakbilBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: MustakbilValidationSettings | None = None) -> None:
        self._settings = settings or MustakbilValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawMustakbilJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Mustakbil",
        )

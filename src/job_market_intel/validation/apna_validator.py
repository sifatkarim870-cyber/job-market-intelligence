"""Batch validation for the Apna scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

The one thing that needs care here is the description floor. Every other
validator in this project treats a description under 100 characters as missing,
and on a board with 2-6k character postings that is a reasonable proxy for "the
parser found nothing". On Apna it is not: measured over 30 postings,
descriptions ran 23-4282 characters with a mean of 835, and **16 of 30 were
under 100 characters** -- the site simply writes terse one-liners for a lot of
retail and fresher roles. A 100-character floor would fail more than half of a
perfectly healthy batch and train everyone to ignore the check.

The floor here is therefore 20 characters, just under the measured minimum of
23, so it asks "is there a description at all" and nothing more. The field
census still reports every posting missing a description, which is where a real
regression would show up.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.apna.models import RawApnaJob
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    # See the module docstring: 16 of 30 measured descriptions are under 100
    # characters, so that floor is not a validity test on this board.
    "description": lambda job: not job.description or len(job.description) < 20,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location and not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    # Measured 30/30, so absence here means the markup changed rather than that
    # employers withheld a number -- which is why Apna is the best salary source
    # in the corpus and why this one IS required.
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
    # Measured 15/30, so counted but never required.
    "skills": lambda job: not job.skills,
}


class ApnaValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``APNA_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="APNA_VALIDATION_", extra="ignore")

    #: A listing page yields 25 distinct postings, so anything below 25 means
    #: discovery broke early rather than that the board was quiet.
    min_expected_jobs: int = 25
    #: 25 postings per page and a first-page walk, so a high skip rate means the
    #: parser is dropping records.
    max_skip_rate: float = 0.25


class ApnaBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: ApnaValidationSettings | None = None) -> None:
        self._settings = settings or ApnaValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawApnaJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Apna",
        )

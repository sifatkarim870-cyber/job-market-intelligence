"""Batch validation for the Careers24 scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

Careers24 needs one check the other schema.org sources do not, because its
``baseSalary`` is a **single scalar** rather than a ``minValue``/``maxValue``
pair. A parser written for the pair shape -- which is what Wellfound and Built
In emit -- reads no salary here at all, and the batch still looks healthy,
because salaries are not required. So the census records salary presence
separately and :mod:`.parser` keeps the observed shape (``salary_shape``) in
the raw payload, which makes a silent drop to zero salary rows visible in the
data instead of only in a coverage number.

``description`` *is* required: Careers24 descriptions measured 217-627 chars,
and a batch with none of them means the JSON-LD extraction stopped finding the
``JobPosting`` at all.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.careers24.models import RawCareers24Job
from job_market_intel.validation.common import validate_batch

#: Field name -> predicate returning True when the field is MISSING.
_MISSING_FIELD_CHECKS: dict[str, Any] = {
    "source_job_id": lambda job: not job.source_job_id or not job.source_job_id.strip(),
    "title": lambda job: not job.title or not job.title.strip(),
    # 100 chars, not the ~600 some boards carry. Careers24 descriptions
    # measured 217-627 chars, and the floor here is the low end of that range
    # rather than a round number, so a legitimate short posting is not culled.
    "description": lambda job: not job.description or len(job.description) < 100,
    "company_name": lambda job: not job.company_name or not job.company_name.strip(),
    "location": lambda job: not job.location and not job.country,
    "posted_date": lambda job: job.posted_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "url": lambda job: not job.url or not job.url.strip(),
    # Not required -- absent on 6 of 8 postings measured -- but counted, so
    # "salary coverage collapsed" is a number and not a hunch.
    "salary": lambda job: job.salary_min is None,
}


class Careers24ValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``CAREERS24_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="CAREERS24_VALIDATION_", extra="ignore")

    #: A listing page yields 10 distinct adverts, so anything below 10 means
    #: discovery broke early rather than that the board was quiet.
    min_expected_jobs: int = 10
    #: 10 adverts per page and a first-page walk, so a high skip rate means the
    #: parser is dropping records.
    max_skip_rate: float = 0.25


class Careers24BatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: Careers24ValidationSettings | None = None) -> None:
        self._settings = settings or Careers24ValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawCareers24Job]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Careers24",
        )

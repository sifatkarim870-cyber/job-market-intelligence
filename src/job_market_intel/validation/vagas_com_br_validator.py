"""Batch validation for the Vagas.com.br scraper.

Same shape as every other source's validator: a batch-level health report that
never raises, plus a missing-field census.

``validate_batch`` does **not** gate ``passed`` on missing fields -- only record
counts, skip rate and duplicate ids. A per-field regression therefore shows up
in ``missing_field_rates``, not in ``passed``, which is why the tests assert on
the census.

``employment_type`` is deliberately **not** in the census: the board publishes
no ``employmentType`` at all (0 of 3 measured), so a check there would be a
permanent 100% failure that says nothing about the parser.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.vagas_com_br.models import RawVagasComBrJob
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
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
}


class VagasComBrValidationSettings(BaseSettings):
    """Thresholds for batch health, tunable via ``VAGAS_COM_BR_VALIDATION_*``."""

    model_config = SettingsConfigDict(env_prefix="VAGAS_COM_BR_VALIDATION_", extra="ignore")

    #: A listing page yields 40 distinct postings, so anything below 40 means
    #: discovery broke early rather than that the board was quiet.
    min_expected_jobs: int = 40
    #: One page per path and a first-hit-wins walk, so a high skip rate means
    #: the parser is dropping records.
    max_skip_rate: float = 0.25


class VagasComBrBatchValidator:
    """Evaluates one fetch+parse cycle."""

    def __init__(self, settings: VagasComBrValidationSettings | None = None) -> None:
        self._settings = settings or VagasComBrValidationSettings()

    def validate(self, raw_jobs: list[dict], parsed_jobs: list[RawVagasComBrJob]):
        """Produce a health report for one batch. Never raises."""
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Vagas.com.br",
        )

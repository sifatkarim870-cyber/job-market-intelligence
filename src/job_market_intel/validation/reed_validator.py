"""Batch-level validation for a single Reed scrape run.

Mirrors ``validation/remotive_validator.py``'s role exactly — see
``validation/remoteok_validator.py``'s docstring for the full rationale on
why batch-level checks are a separate layer from
``scrapers/reed/parser.py``'s per-record validation. This module is a thin
wrapper supplying Reed's own thresholds (``ReedValidationSettings``) and
Reed's own missing-field checks, calling the shared
``validation.common.validate_batch``.

``RawReedJob`` imported only under ``TYPE_CHECKING``, same circular-import
reason documented at length in ``remoteok_validator.py``'s module
docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.reed.models import RawReedJob

#: Fields checked for the informational "missing-field rate" report.
#: Each value is a predicate: given a parsed job, does it count as missing
#: this field? ``employment_type_raw`` here checks the three RAW fields
#: together (not the mapped ``employment_type_code``, which lives on
#: ``CleanedJob``, a later pipeline stage this validator runs before) —
#: since ``ReedCleaner`` treats "none of these three reported" as an
#: honest, expected absence for jobs Details wasn't available for, this
#: is genuinely informational, not a pass/fail signal.
_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "currency_iso_code": lambda job: job.currency_iso_code is None,
    "pay_period_raw": lambda job: job.pay_period_raw is None,
    "employment_type_raw": lambda job: (
        job.contract_type_raw is None and job.full_time is None and job.part_time is None
    ),
    "posting_date": lambda job: job.posting_date is None,
}


class ReedValidationSettings(BaseSettings):
    """Configurable thresholds for Reed batch validation.

    Attributes:
        min_expected_jobs: Below this many successfully parsed jobs, a
            run is flagged as suspiciously small. Left conservative (1)
            rather than calibrated against a real production run's
            volume, since — unlike RemoteOK/Remotive's single
            all-postings feed — Reed's actual per-run volume depends
            entirely on ``scrapers/reed/search_queries.py``'s still-
            unconfirmed query list (see that module's docstring) and
            ``ReedSettings.max_jobs_processed_per_run``. Revisit once a
            real query list and real run history exist, same way
            ``RemotiveValidationSettings.min_expected_jobs`` documents
            having been calibrated from an actual observed run.
        max_skip_rate: Above this fraction of raw records failing
            per-record validation (see ``ReedParser``), a run is flagged.
            Same default as every other source's validator — a few
            skipped records is normal; a sudden jump usually means a
            field was renamed upstream.
    """

    model_config = SettingsConfigDict(
        env_prefix="REED_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    min_expected_jobs: int = Field(default=1, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class ReedBatchValidator:
    """Evaluates whether a completed Reed fetch+parse cycle is healthy.

    A thin wrapper around ``validation.common.validate_batch``: supplies
    Reed's own thresholds and missing-field checks, and nothing else.
    """

    def __init__(self, settings: ReedValidationSettings | None = None) -> None:
        """Create a validator.

        Args:
            settings: Thresholds to use. If omitted, ``ReedValidationSettings()``
                is constructed with its defaults (and any ``REED_VALIDATION_``-
                prefixed overrides present in the environment/``.env`` file).
        """
        self._settings = settings or ReedValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawReedJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report.

        Args:
            raw_jobs: The combined ``{"search": ..., "details": ...}``
                records handed to ``ReedParser.parse_jobs()`` (used here
                only for its length, same as every other source).
            parsed_jobs: The output of ``ReedParser.parse_jobs(raw_jobs)``.

        Returns:
            A ``BatchValidationReport`` describing the batch's health.
            Never raises — see ``validate_batch`` for why.
        """
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Reed",
        )

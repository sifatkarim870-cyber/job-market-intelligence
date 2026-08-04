"""Batch-level validation for a single RemoteOK scrape run.

Why this is a separate layer from ``scrapers/remoteok/parser.py``: the
parser validates *records*, one at a time — does this specific job have a
title, a company, a URL? It has no way to know whether the *batch* as a
whole looks healthy. A run that returns 4 jobs instead of the usual ~100
would pass every per-record check with zero errors, since each of those 4
records can be perfectly valid on its own — but it is still a broken run
(rate-limited, feed shape changed, partial network failure). This module
catches that category of problem: things only visible by looking at the
whole batch at once, not any single record.

Scope for Step 7, deliberately:
    - Volume sanity (did we get a plausible number of jobs at all?)
    - Skip-rate sanity (did an unusually large fraction of records fail
      per-record validation, suggesting RemoteOK changed something?)
    - Within-batch duplicate ``source_job_id`` detection (RemoteOK should
      never return the same job twice in one response)
    - Missing-field rates for analytically important optional fields
      (salary, location, description, tags, posting date) — reported as
      informational statistics, NOT pass/fail criteria. There is no
      baseline yet for what a "normal" missing-salary rate looks like on
      this feed; hard thresholds here would be guessing. Once enough real
      runs have accumulated (naturally, once Step 13's scheduler is
      running this regularly), these could graduate into thresholds too.

This module does not touch the database and does not know about later
pipeline stages (cleaning, normalization) — it only judges whether a
completed fetch+parse cycle is trustworthy enough to hand to the next step.
"""

from __future__ import annotations

from collections import Counter

from loguru import logger
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob

#: Fields checked for the informational "missing-field rate" report.
#: Each value is a predicate: given a parsed job, does it count as missing
#: this field? Kept as a module-level dict (not hardcoded inline) so a new
#: field can be added here without touching the validation logic itself.
_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "tags": lambda job: len(job.tags) == 0,
    "posting_date": lambda job: job.posting_date is None,
}


class RemoteOKValidationSettings(BaseSettings):
    """Configurable thresholds for RemoteOK batch validation.

    Attributes:
        min_expected_jobs: Below this many successfully parsed jobs, a run
            is flagged as suspiciously small. RemoteOK's live feed has
            been observed returning roughly 100 jobs per fetch; this
            default is set well below that so ordinary day-to-day
            fluctuation doesn't trigger false alarms, while still catching
            a genuinely broken run (e.g. a handful of jobs, or zero).
            Revisit this once real scheduled-run history exists (Step 13).
        max_skip_rate: Above this fraction of raw records failing
            per-record validation (see ``RemoteOKParser``), a run is
            flagged. A *few* skipped records is normal and expected
            (RemoteOK's feed is not a documented, guaranteed contract);
            a sudden jump usually means a field was renamed or removed
            upstream.
    """

    model_config = SettingsConfigDict(
        env_prefix="REMOTEOK_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    min_expected_jobs: int = Field(default=20, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class BatchValidationReport(BaseModel):
    """Summary of one RemoteOK fetch+parse cycle's health.

    Attributes:
        total_raw_records: Number of job-shaped records received from
            ``RemoteOKClient.fetch_raw_jobs()`` (the non-job metadata entry
            is already excluded by that point).
        total_parsed: Number of records that passed per-record validation
            in ``RemoteOKParser``.
        total_skipped: ``total_raw_records - total_parsed``.
        skip_rate: ``total_skipped / total_raw_records``, or ``0.0`` if
            there were no raw records at all (avoids division by zero).
        duplicate_source_job_ids: Any ``source_job_id`` values that
            appeared more than once among the *parsed* records.
        missing_field_rates: For each field in ``_MISSING_FIELD_CHECKS``,
            the fraction of parsed records missing that field. Purely
            informational — see module docstring for why these aren't
            pass/fail criteria yet.
        issues: Human-readable descriptions of every problem found. Empty
            if the batch is healthy.
        passed: ``True`` if and only if ``issues`` is empty.
    """

    total_raw_records: int
    total_parsed: int
    total_skipped: int
    skip_rate: float
    duplicate_source_job_ids: list[str]
    missing_field_rates: dict[str, float]
    issues: list[str]
    passed: bool


class RemoteOKBatchValidator:
    """Evaluates whether a completed RemoteOK fetch+parse cycle is healthy."""

    def __init__(self, settings: RemoteOKValidationSettings | None = None) -> None:
        """Create a validator.

        Args:
            settings: Thresholds to use. If omitted, ``RemoteOKValidationSettings()``
                is constructed with its defaults (and any ``REMOTEOK_VALIDATION_``-
                prefixed overrides present in the environment/``.env`` file).
        """
        self._settings = settings or RemoteOKValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawRemoteOKJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report.

        Args:
            raw_jobs: The raw job-shaped dictionaries as returned by
                ``RemoteOKClient.fetch_raw_jobs()`` (metadata entry already
                excluded).
            parsed_jobs: The output of ``RemoteOKParser.parse_jobs(raw_jobs)``.

        Returns:
            A ``BatchValidationReport`` describing the batch's health.
            Never raises — a validation *failure* is represented in the
            report's ``passed``/``issues`` fields, not as an exception,
            since a caller may reasonably want to log-and-continue,
            log-and-alert, or halt, and that decision belongs to the
            caller (e.g. the scheduler in a later step), not to this
            method.
        """
        total_raw_records = len(raw_jobs)
        total_parsed = len(parsed_jobs)
        total_skipped = total_raw_records - total_parsed
        skip_rate = (total_skipped / total_raw_records) if total_raw_records else 0.0

        id_counts = Counter(job.source_job_id for job in parsed_jobs)
        duplicate_source_job_ids = sorted(
            [source_job_id for source_job_id, count in id_counts.items() if count > 1]
        )

        missing_field_rates = {
            field_name: (
                sum(1 for job in parsed_jobs if check(job)) / total_parsed
                if total_parsed
                else 0.0
            )
            for field_name, check in _MISSING_FIELD_CHECKS.items()
        }

        issues: list[str] = []

        if total_raw_records == 0:
            issues.append(
                "Zero raw records received from RemoteOK. The feed may be down, "
                "rate-limiting this client, or returning an unexpected empty response."
            )

        if total_parsed < self._settings.min_expected_jobs:
            issues.append(
                f"Only {total_parsed} job(s) parsed successfully, below the configured "
                f"minimum of {self._settings.min_expected_jobs}. This may indicate the feed "
                "is degraded, rate-limited, or its shape has changed."
            )

        if skip_rate > self._settings.max_skip_rate:
            issues.append(
                f"Skip rate {skip_rate:.1%} exceeds the configured maximum of "
                f"{self._settings.max_skip_rate:.1%}. RemoteOK's field names or "
                "required-field behavior may have changed — check the parser's "
                "WARNING-level logs for the specific validation errors."
            )

        if duplicate_source_job_ids:
            shown = duplicate_source_job_ids[:10]
            suffix = "..." if len(duplicate_source_job_ids) > 10 else ""
            issues.append(
                f"{len(duplicate_source_job_ids)} duplicate source_job_id(s) found within "
                f"a single batch: {shown}{suffix}. RemoteOK should not return the same job "
                "twice in one feed response."
            )

        report = BatchValidationReport(
            total_raw_records=total_raw_records,
            total_parsed=total_parsed,
            total_skipped=total_skipped,
            skip_rate=skip_rate,
            duplicate_source_job_ids=duplicate_source_job_ids,
            missing_field_rates=missing_field_rates,
            issues=issues,
            passed=(len(issues) == 0),
        )

        if report.passed:
            logger.info(
                "RemoteOK batch validation PASSED: {} parsed, {} skipped ({:.1%} skip rate).",
                total_parsed,
                total_skipped,
                skip_rate,
            )
        else:
            logger.warning(
                "RemoteOK batch validation FAILED with {} issue(s): {}",
                len(issues),
                issues,
            )

        return report

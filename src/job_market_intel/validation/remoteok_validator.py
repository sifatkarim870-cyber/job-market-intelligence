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

As of Step 14, the actual batch-health arithmetic (volume/skip-rate/
duplicate/missing-field checks) lives in ``validation/common.py``'s
``validate_batch`` — a source-agnostic function every future source's
validator will also call. This module is now a thin wrapper supplying
RemoteOK's own thresholds (``RemoteOKValidationSettings``) and RemoteOK's
own missing-field checks (``_MISSING_FIELD_CHECKS``, written against
``RawRemoteOKJob``'s field names).

Note on ``RawRemoteOKJob`` below: it is imported only under
``TYPE_CHECKING``, purely for the type hint on ``validate()``'s
``parsed_jobs`` parameter, never at runtime. This is deliberate, not
incidental: a runtime import here previously created a real circular
import (``scrapers.remoteok`` package -> ``.pipeline`` module -> imports
``job_market_intel.validation`` -> this module -> imports
``scrapers.remoteok.models`` -> forces ``scrapers.remoteok``'s own
``__init__.py`` to finish executing, which is still mid-import at that
point) that only surfaced if something imported ``job_market_intel.validation``
*before* anything had already imported ``job_market_intel.scrapers.remoteok``.
``from __future__ import annotations`` (below) means annotations are
never evaluated at runtime, so the ``TYPE_CHECKING`` guard is sufficient —
no lazy/deferred runtime import is needed here, unlike the pattern used
for ``CleanedRemoteOKJob``/``CleanedJob`` in ``db/job_repository.py``,
where the import previously wasn't ``TYPE_CHECKING``-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
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


class RemoteOKBatchValidator:
    """Evaluates whether a completed RemoteOK fetch+parse cycle is healthy.

    A thin wrapper (Step 14) around ``validation.common.validate_batch``:
    supplies RemoteOK's own thresholds and missing-field checks, and
    nothing else. The actual batch-health logic is shared with every
    other source's validator.
    """

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
            Never raises — see ``validate_batch`` for why.
        """
        return validate_batch(
            raw_records=raw_jobs,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="RemoteOK",
        )

"""Batch-level validation for a single Remotive scrape run.

Mirrors ``validation/remoteok_validator.py``'s role exactly — see that
module's docstring for the full rationale on why batch-level checks are a
separate layer from ``scrapers/remotive/parser.py``'s per-record
validation. This module is a thin wrapper supplying Remotive's own
thresholds (``RemotiveValidationSettings``) and Remotive's own
missing-field checks, calling the shared ``validation.common.validate_batch``.

Note on ``RawRemotiveJob`` below: imported only under ``TYPE_CHECKING``,
for the same circular-import reason documented at length in
``remoteok_validator.py``'s module docstring
(``scrapers.remotive`` -> ``.pipeline`` -> ``job_market_intel.validation``
-> this module -> ``scrapers.remotive.models`` would otherwise force
``scrapers.remotive``'s own still-executing ``__init__.py`` to finish
early). ``from __future__ import annotations`` makes the ``TYPE_CHECKING``
guard sufficient — no runtime import is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.remotive.models import RawRemotiveJob

#: Fields checked for the informational "missing-field rate" report.
#: Each value is a predicate: given a parsed job, does it count as missing
#: this field? Mirrors ``remoteok_validator.py``'s
#: ``_MISSING_FIELD_CHECKS`` shape, adapted to Remotive's own field names —
#: notably ``tags`` here reflects the live-shape uncertainty documented in
#: ``scrapers/remotive/models.py``'s module docstring: if Remotive's API
#: turns out not to send tags at all, every job will show as "missing"
#: this field, which is itself useful, honest signal once real run history
#: exists, not a bug to suppress.
_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "salary": lambda job: job.salary_min is None and job.salary_max is None,
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "tags": lambda job: len(job.tags) == 0,
    "posting_date": lambda job: job.posting_date is None,
}


class RemotiveValidationSettings(BaseSettings):
    """Configurable thresholds for Remotive batch validation.

    Attributes:
        min_expected_jobs: Below this many successfully parsed jobs, a run
            is flagged as suspiciously small. Set to 10 based on a real
            live run (Step 18 verification, August 2026): Remotive's
            public API returned only 19 jobs with no ``limit`` parameter
            set, well below what "all currently active listings" would
            suggest. The most likely explanation, based on the API's own
            landing page showing an "Unlock All Jobs" paywall banner
            alongside a much larger total job count advertised elsewhere
            on the site: the free public API now returns only a small,
            unpaywalled subset of the full job board, not everything.
            10 leaves headroom below that observed real-world figure
            while still catching a genuine outage (e.g. 0-2 jobs).
        max_skip_rate: Above this fraction of raw records failing
            per-record validation (see ``RemotiveParser``), a run is
            flagged. A few skipped records is normal and expected; a
            sudden jump usually means a field was renamed or removed
            upstream.
    """

    model_config = SettingsConfigDict(
        env_prefix="REMOTIVE_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    min_expected_jobs: int = Field(default=10, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class RemotiveBatchValidator:
    """Evaluates whether a completed Remotive fetch+parse cycle is healthy.

    A thin wrapper around ``validation.common.validate_batch``: supplies
    Remotive's own thresholds and missing-field checks, and nothing else.
    The actual batch-health logic is shared with every other source's
    validator.
    """

    def __init__(self, settings: RemotiveValidationSettings | None = None) -> None:
        """Create a validator.

        Args:
            settings: Thresholds to use. If omitted, ``RemotiveValidationSettings()``
                is constructed with its defaults (and any ``REMOTIVE_VALIDATION_``-
                prefixed overrides present in the environment/``.env`` file).
        """
        self._settings = settings or RemotiveValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawRemotiveJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report.

        Args:
            raw_jobs: The raw job-shaped dictionaries as returned by
                ``RemotiveClient.fetch_raw_jobs()``.
            parsed_jobs: The output of ``RemotiveParser.parse_jobs(raw_jobs)``.

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
            source_label="Remotive",
        )

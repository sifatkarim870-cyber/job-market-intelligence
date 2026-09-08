"""Batch-level validation for a single We Work Remotely scrape run.

See ``validation/remoteok_validator.py``'s module docstring for why
this is a separate layer from per-record parsing, and why the actual
batch-health arithmetic lives in ``validation/common.py``'s
``validate_batch`` rather than here — this module is a thin wrapper
supplying We Work Remotely's own thresholds
(``WWRValidationSettings``) and its own missing-field checks
(``_MISSING_FIELD_CHECKS``, written against ``RawWWRJob``'s field
names). Everything in that reasoning applies unchanged to this source.

One deliberate omission worth calling out: unlike RemoteOK's
missing-field checks, there is no "salary" entry here. We Work
Remotely's feed has no structured salary field at all (see
``scrapers/weworkremotely/models.py``'s module docstring) — every WWR
job is *always* missing salary at this pipeline stage, by design, not by
chance. Reporting a permanent, unconditional 100% missing-rate for a
field the source structurally never provides would just be noise on
every single run forever, not a useful health signal. Instead, two
fields WWR provides that RemoteOK never did — ``company_logo_url`` and
``closing_date`` — are tracked here, since their presence genuinely
varies posting to posting and is worth watching.

``RawWWRJob`` is imported only under ``TYPE_CHECKING``, for the same
circular-import reason documented at length in
``validation/remoteok_validator.py``'s docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.weworkremotely.models import RawWWRJob

#: Fields checked for the informational "missing-field rate" report.
#: See the module docstring for why there is no "salary" entry here.
_MISSING_FIELD_CHECKS = {
    "country_raw": lambda job: not job.country_raw or not job.country_raw.strip(),
    "skills": lambda job: len(job.skills) == 0,
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "posting_date": lambda job: job.posting_date is None,
    "closing_date": lambda job: job.closing_date is None,
    "company_logo_url": lambda job: job.company_logo_url is None,
}


class WWRValidationSettings(BaseSettings):
    """Configurable thresholds for We Work Remotely batch validation.

    Attributes:
        min_expected_jobs: Below this many successfully parsed jobs, a
            run is flagged as suspiciously small. Unlike RemoteOK's
            ``min_expected_jobs`` (calibrated against an observed ~100
            jobs/fetch), this default is a conservative placeholder, not
            an observed figure — We Work Remotely's single "all jobs"
            feed's typical item count was not confirmed against enough
            real fetches to set a tighter number confidently. Revisit
            once real scheduled-run history exists for this source, same
            as RemoteOK's own note above.
        max_skip_rate: Above this fraction of raw records failing
            per-record validation (see ``WWRParser``), a run is flagged.
            Reused RemoteOK's default absent any WWR-specific evidence
            to justify a different number yet.
    """

    model_config = SettingsConfigDict(
        env_prefix="WWR_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    min_expected_jobs: int = Field(default=10, ge=0)
    max_skip_rate: float = Field(default=0.10, ge=0.0, le=1.0)


class WWRBatchValidator:
    """Evaluates whether a completed We Work Remotely fetch+parse cycle is healthy.

    A thin wrapper around ``validation.common.validate_batch``: supplies
    We Work Remotely's own thresholds and missing-field checks, and
    nothing else. The actual batch-health logic is shared with every
    other source's validator.
    """

    def __init__(self, settings: WWRValidationSettings | None = None) -> None:
        """Create a validator.

        Args:
            settings: Thresholds to use. If omitted, ``WWRValidationSettings()``
                is constructed with its defaults (and any ``WWR_VALIDATION_``-
                prefixed overrides present in the environment/``.env`` file).
        """
        self._settings = settings or WWRValidationSettings()

    def validate(
        self,
        raw_jobs: list[dict],
        parsed_jobs: list[RawWWRJob],
    ) -> BatchValidationReport:
        """Evaluate one fetch+parse cycle and produce a validation report.

        Args:
            raw_jobs: The raw job-shaped dictionaries as returned by
                ``WWRClient.fetch_raw_jobs()``.
            parsed_jobs: The output of ``WWRParser.parse_jobs(raw_jobs)``.

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
            source_label="We Work Remotely",
        )

"""Batch-level validation for a single Indeed scraper session.

Same division of responsibility as remoteok_validator.py (see its module
docstring for the full rationale this mirrors): scrapers/indeed/parser.py
validates individual cards; this module judges whether the session as a
whole looks healthy, calling the shared validation/common.py::validate_batch
engine with Indeed's own thresholds and missing-field checks.

One genuine difference from the three feed-based sources: "how many jobs
should a run produce" has no single right answer for Indeed the way
RemoteOK's ~100-per-fetch feed does — it depends entirely on
max_search_pages_per_session and how many cards a given (query, location)
combination actually has. min_expected_jobs below is set low and mainly
guards against the degenerate case (a session that visited pages but
extracted ~nothing, which usually means the CSS selectors in parser.py
have drifted from Indeed's current markup — see parser.py's own honesty
note about that) rather than flagging a small-but-genuine result count as
unhealthy.

RawIndeedJob is imported only under TYPE_CHECKING, for the same reason and
by the same fix documented in remoteok_validator.py's module docstring
(avoiding a scrapers.indeed <-> validation circular import).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .common import BatchValidationReport, validate_batch

if TYPE_CHECKING:
    from job_market_intel.scrapers.indeed.models import RawIndeedJob

#: Fields checked for the informational "missing-field rate" report.
#: description_raw is expected to be missing for a real fraction of
#: records by design (sponsored cards, and organic cards whose detail
#: page wasn't visited within this session's max_detail_pages_per_session
#: cap) — included anyway because tracking that rate over time is exactly
#: how a genuine detail-page parsing regression (vs. normal session-cap
#: behavior) would be noticed.
_MISSING_FIELD_CHECKS = {
    "location_raw": lambda job: not job.location_raw or not job.location_raw.strip(),
    "salary_text": lambda job: job.salary_text is None,
    "description_raw": lambda job: not job.description_raw or not job.description_raw.strip(),
    "detail_url": lambda job: job.detail_url is None,
}


class IndeedValidationSettings(BaseSettings):
    """Configurable thresholds for Indeed batch validation.

    Attributes:
        min_expected_jobs: Below this many successfully parsed jobs in a
            session, the run is flagged as suspiciously small — see module
            docstring for why this is deliberately low rather than tuned
            to any expected page/query volume.
        max_skip_rate: Above this fraction of raw cards failing per-record
            validation, a run is flagged. Set slightly more permissive
            than RemoteOK's default — a hand-rolled HTML parser against a
            real, changing site is inherently noisier than a documented
            JSON feed.
    """

    model_config = SettingsConfigDict(
        env_prefix="INDEED_VALIDATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    min_expected_jobs: int = Field(default=3, ge=0)
    max_skip_rate: float = Field(default=0.20, ge=0.0, le=1.0)


class IndeedBatchValidator:
    """Evaluates whether a completed Indeed session's fetch+parse cycle is
    healthy. Thin wrapper over ``validation.common.validate_batch`` —
    same pattern as every other source's validator.
    """

    def __init__(self, settings: IndeedValidationSettings | None = None) -> None:
        self._settings = settings or IndeedValidationSettings()

    def validate(
        self,
        raw_cards: list[dict],
        parsed_jobs: list[RawIndeedJob],
    ) -> BatchValidationReport:
        """Evaluate one session's cards and produce a validation report.

        Args:
            raw_cards: The raw per-card dicts as captured in each parsed
                record's own ``raw_payload`` — passed separately here
                (rather than re-deriving from ``parsed_jobs``) only to
                match the shared ``validate_batch`` signature's
                ``raw_records``/``parsed_records`` split; for Indeed these
                two lists are the same length by construction, since
                cards are validated into a ``RawIndeedJob`` or skipped
                entirely within a single ``parser.py`` pass (see
                ``parser.py``'s ``_parse_card`` — there's no separate
                "raw dict survives, parsed model doesn't" state the way a
                JSON-feed source has).
            parsed_jobs: The records that passed per-card validation.

        Returns:
            A ``BatchValidationReport`` describing the session's health.
        """
        return validate_batch(
            raw_records=raw_cards,
            parsed_records=parsed_jobs,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=self._settings.min_expected_jobs,
            max_skip_rate=self._settings.max_skip_rate,
            source_label="Indeed",
        )

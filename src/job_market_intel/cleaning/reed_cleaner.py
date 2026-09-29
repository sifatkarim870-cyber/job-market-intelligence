"""Cleans validated Reed records into standardized, storage-ready records.

See ``cleaning/remoteok_cleaner.py``'s module docstring for the overall
boundary this module keeps: it takes a validated-but-still-messy
``RawReedJob`` and produces a ``CleanedJob`` (``cleaning/common.py``),
same "only remove noise with no analytical value, never make judgment
calls about meaning" principle, and the same explicit list of things this
deliberately does NOT do (company resolution, geographic resolution,
skill extraction, currency conversion, content-hash computation — all
later, separate steps).

This is the first cleaner to populate ``CleanedJob.currency_iso_code``/
``pay_period``/``employment_type_code`` with real, per-record,
source-reported values rather than a source-wide constant — see
``db/job_repository.py``'s module docstring ("Reed scraper note") for the
full history of why those fields exist at all.

Confirmed mapping decisions (Fahim, during scoping — not re-derived here)
---------------------------------------------------------------------------
- ``salaryType`` -> ``pay_period``: ``"per annum"``/``"per day"`` confirmed
  live; ``"per hour"``/``"per week"``/``"per month"`` documented by Reed
  but not yet observed live — see ``_map_pay_period``.
- ``contractType``/``fullTime``/``partTime`` -> ``employment_type_code``:
  ``contractType`` wins when it's ``contract``/``temporary``; otherwise
  fall back to ``fullTime``/``partTime``. A "permanent, part-time" job
  loses the "permanent" distinction — a known, accepted gap, not solved
  here (Fahim's own words: "not something to solve by redesigning the
  schema right now") — see ``_map_employment_type``.
- Undisclosed-salary GBP default: when Reed doesn't report a currency at
  all (confirmed live: happens even on Details, for jobs with no
  disclosed salary), this cleaner defaults to ``"GBP"`` rather than
  leaving ``CleanedJob.currency_iso_code`` unset. Correction from an
  earlier assumption: Reed is NOT exclusively a UK job board — confirmed
  via reed.co.uk/internationaljobs, it hosts a real (if minority, ~4% of
  volume) set of international postings across Europe and worldwide. The
  ``"GBP"`` default is still reasonable as a default (Reed's overwhelming
  majority is UK/GBP) but is a convenience default, not a claim about
  every job on the platform. It's also harmless regardless: when
  ``salary_min``/``salary_max`` are both ``None`` (as they are whenever
  currency is missing), ``normalize_annual_salary`` never uses the
  currency for anything. Confirmed decision #4 (leave
  ``normalized_annual_*_usd`` NULL rather than hardcode an FX rate)
  covers the DISCLOSED-GBP-salary case separately — this default is only
  about giving ``CleanedJob`` a non-``None`` value to satisfy its
  required field, not about currency conversion.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.reed.models import RawReedJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

#: Reed's own documented values (confirmed live for the first two;
#: documented by Reed but not yet observed live for the rest — see the
#: module docstring). Matched case-insensitively, stripped, since
#: ``contractType`` was confirmed live to be Title Case
#: (``"Permanent"``) despite Reed's own prose documentation showing
#: lowercase.
_PAY_PERIOD_MAP = {
    "per annum": "yearly",
    "per day": "daily",
    "per hour": "hourly",
    "per week": "weekly",
    "per month": "monthly",
}

#: Reed's own ``contractType`` values that map directly onto
#: ``ref.employment_types.code`` — "permanent" is deliberately absent:
#: there is no ``permanent`` code, so it falls through to the
#: ``fullTime``/``partTime`` check instead. See ``_map_employment_type``.
_CONTRACT_TYPE_MAP = {
    "contract": "contract",
    "temporary": "temporary",
}

#: Harmless placeholder used only when Reed reports no currency at all
#: (always paired with salary_min=salary_max=None) -- see module
#: docstring's "Undisclosed-salary GBP default" note.
_DEFAULT_CURRENCY_ISO_CODE = "GBP"

#: Harmless placeholder used only when Reed reports no salaryType at all
#: (same pairing as above). Chosen for consistency with the other three
#: live sources' own default, not because "yearly" is more likely than
#: any other period for a job with no disclosed salary.
_DEFAULT_PAY_PERIOD = "yearly"


def _map_pay_period(pay_period_raw: str | None) -> str:
    """Map Reed's ``salaryType`` string onto the schema's pay_period vocabulary.

    Returns ``_DEFAULT_PAY_PERIOD`` (logged only when ``pay_period_raw``
    is a genuinely unrecognized non-``None`` string -- a real "Reed sent
    something we don't have a mapping for yet" signal, not the routine
    "no salary disclosed" case, which is silent).
    """
    if pay_period_raw is None:
        return _DEFAULT_PAY_PERIOD
    normalized = pay_period_raw.strip().lower()
    mapped = _PAY_PERIOD_MAP.get(normalized)
    if mapped is None:
        logger.warning(
            "Unrecognized Reed salaryType {!r} -- no mapping exists yet. "
            "Falling back to {!r}; the real value is still preserved in raw_payload.",
            pay_period_raw,
            _DEFAULT_PAY_PERIOD,
        )
        return _DEFAULT_PAY_PERIOD
    return mapped


def _map_employment_type(
    *, full_time: bool | None, part_time: bool | None, contract_type_raw: str | None
) -> str | None:
    """Map Reed's contractType/fullTime/partTime onto ref.employment_types.code.

    Confirmed precedence (see module docstring): ``contractType`` wins
    when it's ``contract``/``temporary``; otherwise fall back to
    ``fullTime``/``partTime``. Returns ``None`` when none of these were
    reported at all (Details wasn't available for this job — an honest
    absence, matching every other source's default).
    """
    if contract_type_raw:
        mapped = _CONTRACT_TYPE_MAP.get(contract_type_raw.strip().lower())
        if mapped is not None:
            return mapped
        if contract_type_raw.strip().lower() != "permanent":
            logger.warning(
                "Unrecognized Reed contractType {!r} -- falling back to "
                "fullTime/partTime. The real value is still preserved in raw_payload.",
                contract_type_raw,
            )
    if full_time is True:
        return "full_time"
    if part_time is True:
        return "part_time"
    return None


#: Minimum word count for a description to count as "substantial" in the
#: completeness score below. Reused unchanged from
#: ``remoteok_cleaner._SUBSTANTIAL_DESCRIPTION_WORD_COUNT`` — see that
#: constant's docstring for the rationale, which applies identically here.
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Compute a 0.0-1.0 completeness score from already-cleaned fields.

    The exact same four-signal, equally-weighted formula every other
    source's cleaner uses — see ``remotive_cleaner``'s copy of this
    docstring for why reusing the identical weighting keeps the score
    comparable across sources. One honest consequence worth knowing,
    specific to Reed: ``skills`` is always empty here (Reed's API has no
    tags/skills field at all — confirmed during scoping), so this signal
    is always absent for every Reed job, same honest-gap treatment as any
    other missing signal, not a defect to work around.
    """
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


class ReedCleaner:
    """Cleans a batch of validated Reed records into CleanedJob records."""

    def clean_job(self, raw_job: RawReedJob) -> CleanedJob:
        """Clean a single validated Reed job record.

        Args:
            raw_job: A ``RawReedJob`` produced by ``ReedParser``.

        Returns:
            The corresponding ``CleanedJob``.
        """
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        salary_disclosed = raw_job.salary_min is not None or raw_job.salary_max is not None
        word_count = len(description_clean.split()) if description_clean else 0

        # Reed sends decimal salary values (e.g. 75000.0000); CleanedJob's
        # salary_min/salary_max are int, matching the other three sources.
        # Every real value observed live during scoping was a whole
        # number, but round() (rather than int(), which truncates) is
        # used defensively in case a genuine fractional value (e.g. a
        # £450.50 day rate) ever appears -- logged when rounding actually
        # changes the value, so a real loss of precision is visible
        # rather than silent.
        salary_min = _round_salary(raw_job.salary_min, raw_job.source_job_id, "salary_min")
        salary_max = _round_salary(raw_job.salary_max, raw_job.source_job_id, "salary_max")

        employment_type_code = _map_employment_type(
            full_time=raw_job.full_time,
            part_time=raw_job.part_time,
            contract_type_raw=raw_job.contract_type_raw,
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=None,  # Reed's API has no company logo field
            # Reed's API has no skills/tags field at all -- an honest
            # absence, not a parsing gap, unlike RemoteOK/Remotive's tags.
            skills=[],
            location_cleaned=location_cleaned,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            # Falls back to original_url when Reed provides no distinct
            # externalUrl -- same fallback behavior every other source's
            # cleaner applies for a job with only one URL.
            apply_url=raw_job.apply_url or raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            closing_date=raw_job.closing_date,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=[],
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            currency_iso_code=raw_job.currency_iso_code or _DEFAULT_CURRENCY_ISO_CODE,
            pay_period=_map_pay_period(raw_job.pay_period_raw),
            employment_type_code=employment_type_code,
        )

    def clean_jobs(self, raw_jobs: list[RawReedJob]) -> list[CleanedJob]:
        """Clean a batch of validated Reed job records.

        Mirrors every other source's cleaner's skip-don't-crash
        philosophy exactly — every input record already passed schema
        validation, so a cleaning failure here is unexpected, but one
        unexpected error should still not take down the rest of an
        otherwise-healthy batch.

        Args:
            raw_jobs: Validated records from ``ReedParser.parse_jobs()``.

        Returns:
            Cleaned records. May be shorter than ``raw_jobs`` if any
            individual record failed to clean (logged when this happens).
        """
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
                logger.error(
                    "Unexpected error cleaning Reed job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Reed cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs


def _round_salary(value: float | None, source_job_id: str, field_name: str) -> int | None:
    """Round a Reed salary figure to the nearest int, logging any real precision loss."""
    if value is None:
        return None
    rounded = round(value)
    if rounded != value:
        logger.warning(
            "Reed job {} {} had a fractional value ({}); rounded to {}.",
            source_job_id,
            field_name,
            value,
            rounded,
        )
    return rounded

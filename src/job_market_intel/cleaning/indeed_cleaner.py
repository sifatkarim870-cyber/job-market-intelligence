"""Cleans validated Indeed records into standardized, storage-ready records.

Follows remoteok_cleaner.py's own structure and division of responsibility
exactly (see that module's docstring for the general "what a cleaner does
vs. doesn't do" boundary — company resolution, geographic resolution,
skill extraction, and content-hash computation are all later/separate
steps here too, not this module's job).

Two things are genuinely different about Indeed, flagged rather than
silently worked around, matching this project's own established posture
(see db/job_repository.py's _ASSUMED_PAY_PERIOD/_ASSUMED_CURRENCY_ISO_CODE
constants and their docstrings for the precedent):

1. Salary period. RemoteOK/Remotive/WWR are annual-USD by construction of
   their own raw data, which is exactly why job_repository.py's
   _ASSUMED_PAY_PERIOD = "yearly" is currently a safe, if unverified-per-
   record, assumption. Indeed shows salary at whatever cadence the poster
   used — "a year", "an hour", "a month" all appear on real listings. This
   cleaner only ever populates salary_min/salary_max for postings
   explicitly labeled annual ("a year"/"per year"/"annually"); an hourly,
   weekly, monthly, or daily rate is left undisclosed
   (salary_min=salary_max=None, salary_disclosed=False) rather than
   silently multiplied into an annual figure, because that multiplication
   is a real analytical decision (which multiplier? does a "$45/hr,
   contract" posting even belong in the same normalized_annual_min_usd
   column as a salaried role?) that belongs in normalization/
   salary_standardization.py once it's extended to reason about pay
   period, not smuggled into a text cleaner. The raw text survives either
   way in raw_payload, so nothing is lost — it's just not stored as if it
   were an annual figure until that's actually correct.

2. Fields with no CleanedJob column yet. employment_type_text, benefits,
   is_sponsored, is_easy_apply, and posted_text all come through on
   RawIndeedJob (see its own docstring) but CleanedJob (cleaning/common.py)
   has no field for any of them — core.jobs.employment_type_id and
   bridge.job_benefits exist in the schema, but nothing in the current
   cleaning/persistence pipeline (for any of the three live sources
   either) populates them yet. This cleaner preserves all five in
   CleanedJob.raw_payload rather than dropping them, so promoting them
   into the schema later is a matter of extending CleanedJob and
   job_repository.py, not re-scraping.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from loguru import logger

from job_market_intel.scrapers.indeed.models import RawIndeedJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

#: Matches a dollar amount like "$77,322.59" or "$45" — the digit group
#: this module's salary parser pulls two of (a range) or one of (a single
#: figure) out of Indeed's free-text salary strings.
_AMOUNT_PATTERN = re.compile(r"\$([\d,]+(?:\.\d+)?)")

#: Phrases that mark a salary string as annual. Matched case-insensitively
#: against the whole string. Deliberately narrow (see module docstring) —
#: anything not matching one of these is treated as "pay period not
#: confirmed as annual," not as "assume annual."
_ANNUAL_MARKERS = ("a year", "per year", "annually", "/yr", "/year")


def _parse_amount(text: str) -> int | None:
    cleaned = text.replace(",", "")
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_annual_salary(salary_text: str | None) -> tuple[int | None, int | None]:
    """Best-effort parse of an explicitly-annual Indeed salary string into
    (salary_min, salary_max). Returns (None, None) for anything not
    confirmed annual — see module docstring for why this doesn't guess.
    """
    if salary_text is None:
        return None, None
    lowered = salary_text.lower()
    if not any(marker in lowered for marker in _ANNUAL_MARKERS):
        logger.debug("Indeed salary text not confirmed annual, skipping: {}", salary_text)
        return None, None

    amounts = [_parse_amount(m) for m in _AMOUNT_PATTERN.findall(salary_text)]
    confirmed_amounts: list[int] = [a for a in amounts if a is not None]
    if not confirmed_amounts:
        return None, None
    if len(confirmed_amounts) == 1:
        return confirmed_amounts[0], confirmed_amounts[0]
    return min(confirmed_amounts), max(confirmed_amounts)


#: Same rationale and same value as remoteok_cleaner.py's identical
#: constant — kept in sync deliberately, not re-derived per source.
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Same four-signal completeness formula as every other source's
    cleaner (see remoteok_cleaner.py's identical function for the full
    rationale) — kept identical across sources deliberately, so
    data_quality_score means the same thing regardless of origin.

    Note that `skills` is always empty for Indeed today (see module
    docstring point 2) and `word_count` depends on whether this record's
    detail page was actually visited this session — both are real,
    expected sources of a lower score for partially-covered records, not
    bugs in this function.
    """
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


class IndeedCleaner:
    """Cleans a batch of validated Indeed records into CleanedJob records."""

    def clean_job(self, raw_job: RawIndeedJob) -> CleanedJob:
        """Clean a single validated Indeed job record.

        Args:
            raw_job: A ``RawIndeedJob`` produced by
                ``scrapers.indeed.parser``.

        Returns:
            The corresponding ``CleanedJob``.
        """
        salary_min, salary_max = _parse_annual_salary(raw_job.salary_text)
        salary_disclosed = salary_min is not None or salary_max is not None
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        word_count = len(description_clean.split()) if description_clean else 0
        skills: list[str] = []  # see module docstring point 2

        # original_url is NOT NULL in the schema (core.jobs.original_url).
        # Sponsored cards (see RawIndeedJob.detail_url's docstring) have no
        # job-specific URL — their ad-redirect is never followed, by
        # confirmed decision — so this falls back to the search results
        # page that produced the card. Not job-specific, but real and
        # traceable, which an empty string wouldn't be.
        original_url = raw_job.detail_url or (
            "https://www.indeed.com/jobs"
            f"?q={quote_plus(raw_job.query_text)}&l={quote_plus(raw_job.location_text)}"
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=None,  # not extracted from the search/detail card today
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw_job.detail_url,
            original_url=original_url,
            posting_date=None,  # Indeed's "posted X days ago" text isn't a parseable date
            # currency_iso_code/pay_period became required CleanedJob
            # fields when the Reed scraper's shared extension landed (see
            # db.job_repository's module docstring, "Reed scraper note").
            # This is the minimum touch needed to keep this module
            # constructing a valid CleanedJob at all -- USD/yearly matches
            # _parse_annual_salary's existing "a year" assumption above
            # (see that function's own docstring), so this changes
            # nothing about what gets stored. No other line in this file
            # was touched for the Reed work.
            currency_iso_code="USD",
            pay_period="yearly",
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
        )

    def clean_jobs(self, raw_jobs: list[RawIndeedJob]) -> list[CleanedJob]:
        """Clean a batch of validated Indeed job records.

        Same skip-don't-crash posture as remoteok_cleaner.py's
        clean_jobs(): every input already passed model validation, so a
        cleaning failure here is unexpected, but one unexpected error must
        never take down an otherwise-healthy batch.

        Args:
            raw_jobs: Validated records from ``scrapers.indeed.parser``.

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
                    "Unexpected error cleaning Indeed job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Indeed cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs

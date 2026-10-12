"""Cleans validated Himalayas records into standardized, storage-ready records.

Follows the same shape as every other cleaner in this package: strip markup,
repair the one mechanical error a feed can produce (swapped salary bounds),
derive the two fields the schema expects (``salary_disclosed``,
``word_count``), and map Himalayas' own vocabulary onto ``CleanedJob``.

Two field mappings worth stating explicitly, because both are guesses about
intent rather than mechanical translations:

``location_cleaned``
    Himalayas reports ``locationRestrictions`` as a list of allowed countries,
    and it is frequently EMPTY -- meaning "open to anyone", not "unknown". An
    empty list therefore becomes the literal string "Worldwide / remote", the
    same wording the corpus already uses elsewhere, so a downstream country
    resolver sees one vocabulary rather than two.

``pay_period``
    ``salaryPeriod`` arrives as "hourly", "monthly" or "yearly". The value is
    passed through rather than assumed, because assuming USD/yearly for a
    source that genuinely reports hourly rates would silently misprice every
    row -- which is the exact bug the Reed scraper was written to fix.

Deliberately NOT done here, matching the other cleaners: company resolution,
geographic resolution to ``ref.locations``, structured skill extraction, and
content hashing. Those run in ``db/job_repository.py`` and the normalization
modules.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.himalayas.models import RawHimalayasJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

#: Mirrors the threshold the other cleaners use, so data_quality_score means
#: the same thing across sources.
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 50

#: Used when ``locationRestrictions`` is empty. Empty means the posting is open
#: to any country, which is a fact about the job -- not missing data.
WORLDWIDE_LOCATION = "Worldwide / remote"

#: ``salary.job_salaries.pay_period`` is constrained to this exact set by
#: ``ck_job_salaries_pay_period``:
#:
#:     CHECK (pay_period IS NULL OR pay_period = ANY
#:            (ARRAY['hourly','daily','weekly','monthly','yearly']))
#:
#: Himalayas sends 'annual' (107 of 120 records sampled on 2026-10-12),
#: 'hourly' (11) and 'monthly' (2). 'annual' is not in the allowed set, so
#: passing it through raises
#:
#:     CheckViolation: new row for relation "job_salaries" violates check
#:     constraint "ck_job_salaries_pay_period"
#:
#: and every row in the batch fails to persist. It is normalised to 'yearly'
#: here, which is the same period the salary normaliser already understands.
_PAY_PERIOD_ALIASES = {
    "annual": "yearly",
    "annually": "yearly",
    "per year": "yearly",
    "per annum": "yearly",
    "year": "yearly",
    "per hour": "hourly",
    "hour": "hourly",
    "per month": "monthly",
    "month": "monthly",
    "per week": "weekly",
    "week": "weekly",
    "per day": "daily",
    "day": "daily",
}

#: The schema's own vocabulary. Anything outside it is stored as NULL rather
#: than guessed at -- a wrong period silently misprices the row, whereas NULL
#: is visibly absent.
_ALLOWED_PAY_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}


def _normalize_pay_period(raw: str | None) -> str | None:
    """Map a feed pay-period onto the schema's allowed set."""
    if not raw:
        return None
    cleaned = raw.strip().lower()
    mapped = _PAY_PERIOD_ALIASES.get(cleaned, cleaned)
    if mapped in _ALLOWED_PAY_PERIODS:
        return mapped
    logger.warning("Himalayas pay_period {!r} is not a schema value; storing NULL", raw)
    return None


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Four-signal completeness score, identical in shape and weighting to
    every other cleaner's, so the number stays comparable across sources."""
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


def _normalize_salary(
    raw: RawHimalayasJob,
) -> tuple[int | None, int | None, bool]:
    """Return (min, max, disclosed), repairing a reversed range.

    Himalayas reports hourly rates for hourly roles (30-70 for one record seen
    on 2026-10-12) and annual figures for salaried ones, so the values are kept
    as given. Only an obviously inverted pair is swapped -- a max below its min
    is always a data-entry error, and leaving it would make every downstream
    average wrong in a way that is invisible in the raw data.
    """
    low = raw.minSalary
    high = raw.maxSalary

    if low is not None and high is not None and low > high:
        logger.debug(
            "Himalayas salary bounds reversed ({} > {}); swapping", low, high
        )
        low, high = high, low

    def as_int(value: float | None) -> int | None:
        return None if value is None else int(round(value))

    disclosed = raw.minSalary is not None or raw.maxSalary is not None
    return as_int(low), as_int(high), disclosed


def _collect_skills(raw: RawHimalayasJob) -> list[str]:
    """Categories and seniority labels, deduplicated, order preserved.

    These are the closest thing Himalayas has to a tag list, and ``ref.skills``
    is the schema's vocabulary for exactly that.
    """
    seen: set[str] = set()
    skills: list[str] = []
    for value in [*raw.categories, *raw.seniority]:
        label = clean_plain_text(value)
        if label and label.lower() not in seen:
            seen.add(label.lower())
            skills.append(label)
    return skills


class HimalayasCleaner:
    """Turns ``RawHimalayasJob`` objects into ``CleanedJob`` records."""

    def clean_jobs(self, jobs: list[RawHimalayasJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        for raw in jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                # One bad record must not end the run; the other postings in
                # the batch are still worth having.
                logger.error(
                    "Failed to clean Himalayas job {}: {}", raw.guid[:80], exc
                )
        return cleaned

    def clean_job(self, raw: RawHimalayasJob) -> CleanedJob:
        description_clean = clean_html_text(raw.description) or clean_plain_text(
            raw.excerpt
        )
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min, salary_max, salary_disclosed = _normalize_salary(raw)
        skills = _collect_skills(raw)
        location_cleaned = raw.location_text or WORLDWIDE_LOCATION

        return CleanedJob(
            source_job_id=raw.guid,
            job_title=clean_plain_text(raw.title) or raw.title,
            company_name=clean_plain_text(raw.companyName) or raw.companyName or "Unknown",
            company_logo_url=raw.companyLogo,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw.applicationLink or raw.guid,
            original_url=raw.guid,
            posting_date=raw.posting_date,
            closing_date=raw.closing_date,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw.raw_payload,
            # Himalayas states the currency per record, so it is passed through
            # as reported rather than assumed. The pay period is NOT: the feed
            # sends 'annual', which ck_job_salaries_pay_period rejects, and an
            # unmapped value fails the whole batch. See _normalize_pay_period.
            currency_iso_code=raw.currency or "USD",
            pay_period=_normalize_pay_period(raw.salaryPeriod),
            employment_type_code=raw.employmentType,
        )

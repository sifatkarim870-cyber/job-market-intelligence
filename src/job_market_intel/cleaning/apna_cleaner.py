"""Cleans raw Apna postings into the shared ``CleanedJob`` contract.

Apna is **India only** and that is measured rather than assumed: all 30 postings
in the census carried ``addressCountry: "IN"`` and ``applicantLocationRequirements:
{"@type": "Country", "name": "India"}``. Both are read from the page.

Two things this board offers that no other source here does:

* **A skills list on real postings.** ``skills`` carried 0-11 short strings on
  15 of 30 postings ("B2B Sales", "Distributor", "SMB sales"). Every other
  source in this project puts an empty list here, so these are the only rows in
  the corpus whose ``skills`` column means anything. The other 15 legitimately
  have none -- measured, not missing.

* **A salary band on every posting.** 30 of 30 carried ``baseSalary``, always
  ``unitText: "MONTH"`` and always INR. This makes Apna the highest-coverage
  salary source in the corpus, and it is also the reason ``pay_period`` is
  ``monthly`` here rather than the ``yearly`` default: every measured figure is
  a monthly one, and storing 180000 as annual would overstate it by twelve
  times.

One measurement worth recording, because it will otherwise look like a bug:
Apna writes **"Bengaluru"** where ``ref.cities`` holds **"Bangalore"**. Both are
correct English names for the same city and the ISO code agrees with the stored
row, but ``city_exact`` will not match on the spelling, so Bengaluru postings
resolve to their state or to country-only. That is a seed-data gap (the city
table needs the variant, or an alias), not a parser fault, and it is left
visible here rather than papered over with a lookup table.

What does *not* survive: ``CleanedJob.raw_payload`` is not persisted by
``JobRepository.save_cleaned_job``, so ``industry``,
``occupationalCategory``, ``experienceRequirements``, ``directApply`` and the
observed ``salary_shape`` ride in the payload and are discarded at save time.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.apna.models import RawApnaJob

#: The only values ``salary.job_salaries.pay_period`` accepts. Anything else
#: violates ``ck_job_salaries_pay_period``, and that violation **aborts the
#: enclosing transaction**, taking every later row with it -- the failure mode
#: that lost 25 of 30 rows on the first Job Bank run.
ALLOWED_PAY_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly", "yearly"})

#: The period used when nothing usable is known. Measured: every Apna salary
#: carrying a period was MONTH, so this only ever applies to a posting with no
#: amount at all. It is "monthly" rather than the "yearly" default the other
#: cleaners use because a yearly default would be wrong for this board.
_FALLBACK_PAY_PERIOD = "monthly"


def _safe_pay_period(value: str | None) -> str:
    """Constrain a pay period to the schema's vocabulary.

    The parser already maps ``unitText`` through a fixed table, so this should
    never fire. It is here because the alternative is not a wrong number in one
    row -- it is a check-constraint violation that aborts the transaction and
    fails **every remaining row in the batch** with it. One unexpected unit
    string from a site would then cost the whole run, so the check is made
    explicit rather than trusted.
    """
    if value in ALLOWED_PAY_PERIODS:
        return value
    if value:
        # No literal braces in this message: loguru renders through
        # str.format, so "{hourly, daily, ...}" would be read as a format field
        # and raise KeyError from inside the logger.
        logger.warning(
            "Apna pay period {!r} is outside the schema vocabulary "
            "(hourly, daily, weekly, monthly, yearly) -- falling back to {}. "
            "The raw value is still preserved in raw_payload.",
            value,
            _FALLBACK_PAY_PERIOD,
        )
    return _FALLBACK_PAY_PERIOD


#: schema.org ``employmentType`` -> ``ref.employment_types.code``. These are the
#: database's codes, not display strings; anything outside this table is left as
#: ``None`` with a warning and the real string stays in ``raw_payload``.
_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "freelance",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "APPRENTICESHIP": "apprenticeship",
    "PER_DIEM": None,
    "OTHER": None,
}


def _map_employment_type(value: str | None) -> str | None:
    """schema.org ``employmentType`` -> a ``ref.employment_types.code``.

    Comma-separated multi-values are read left to right, so the first listed
    contract form wins.
    """
    if not value:
        return None
    for segment in value.split(","):
        key = re.sub(r"[^A-Z]+", "_", segment.strip().upper()).strip("_")
        if not key:
            continue
        if key in _EMPLOYMENT_MAP:
            return _EMPLOYMENT_MAP[key]
    logger.warning(
        "Unrecognized Apna employmentType {!r} -- employment_type_code left "
        "None; the real value is still preserved in raw_payload.",
        value,
    )
    return None


def _clean_description(body: str | None) -> str:
    """Unescape entities and strip any markup from the JSON-LD description.

    Most descriptions measured are plain prose, but some employers paste HTML
    into the structured field, so tags are stripped rather than assumed away.
    """
    if not body:
        return ""
    return clean_html_text(html.unescape(body)) or ""


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _location_label(raw: RawApnaJob) -> str | None:
    """Prefer the joined city/region, fall back to country alone.

    A posting with only a country is still a real location statement, so it is
    kept rather than dropped.
    """
    return raw.location or raw.country or None


def _quality_score(job: RawApnaJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why.

    The description signal is ``>= 100`` chars even though the validator's
    floor is 20: a score should reward a substantial posting, while a pass/fail
    gate must not punish a terse but genuine one.
    """
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location or job.country),
        "description": len(description) >= 100,
        "salary": job.salary_min is not None or job.salary_max is not None,
        "posted_date": job.posted_date is not None,
        "skills": bool(job.skills),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class ApnaCleaner:
    """Turns ``RawApnaJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawApnaJob) -> CleanedJob:
        """Clean one posting."""
        body = _clean_description(raw_job.description)

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_min is not None and salary_max is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "industry": raw_job.industry,
                "occupational_category": raw_job.occupational_category,
                "employment_type": raw_job.employment_type,
                "experience_requirements": raw_job.experience_requirements,
                "direct_apply": raw_job.direct_apply,
                "applicant_country": raw_job.applicant_country,
                "postal_code": raw_job.postal_code,
                "street_address": raw_job.street_address,
                "skills_raw": raw_job.skills,
                "listing_page": raw_job.listing_page,
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            skills=raw_job.skills,
            location_cleaned=_location_label(raw_job),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_min is not None or salary_max is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            # Read from the page, not assumed: all 30 postings measured carried
            # INR.
            currency_iso_code=raw_job.currency_iso_code or "INR",
            # Constrained to the schema vocabulary: an out-of-range value here
            # aborts the transaction and fails every later row in the batch.
            # NOT the "yearly" default the other cleaners use -- all 30 measured
            # salaries were unitText MONTH, and storing a monthly figure as
            # annual would overstate it twelvefold.
            pay_period=_safe_pay_period(raw_job.salary_period),
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawApnaJob]) -> list[CleanedJob]:
        """Clean a batch, logging failures instead of silently dropping them."""
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001 - one bad posting must not stop the batch
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Apna postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Apna posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

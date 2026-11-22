"""Cleans Nationale Vacaturebank raw ads into storage-ready ``CleanedJob`` records.

Nationale Vacaturebank publishes a schema.org ``JobPosting`` block, so the
facts are mapped directly rather than inferred:

* ``baseSalary`` (present on ~78% of ads measured) is the ad's **own** offer,
  in EUR, with ``unitText`` naming the period. The raw ``unitText`` is not
  trusted on its own: the board stamps hourly rates with ``"MONTH"`` (a
  "bruto uurloon van EUR 18,43 - 23,99" ad shipped ``23`` with
  ``unitText: "MONTH"``), so a value far too small for a month is re-read as
  ``hourly`` by the parser. It becomes ``salary_min``/``salary_max`` and
  ``salary_disclosed``. The separate ``Occupation.estimatedSalary`` is the
  board's market estimate, so it is never used here.
* an ad with no ``baseSalary`` is stored salary-undisclosed in EUR with
  ``pay_period="monthly"`` -- the Dutch quoting convention, and a required
  column even when no amount exists.
* ``employmentType`` is usually ``["FULL_TIME", "PART_TIME"]``, the board's
  "either" default. A code is only assigned when the list resolves to exactly
  one type; a mixed list stays ``None`` rather than guessing.
* ``educationRequirements.credentialCategory`` is English ("bachelor degree",
  "associate degree", "high school") and maps onto ``ref.education_levels``.
* ``experienceRequirements.monthsOfExperience`` converts to years and feeds
  the shared ``map_experience_level``; a title such as "Senior ..." still wins,
  as in the other cleaners.
* ``jobLocationType == "TELECOMMUTE"`` is the only remote signal the board
  publishes, and it maps to ``remote_country``. A missing value is left
  ``None`` -- absence is not a statement that the role is on-site.

``location_cleaned`` is the ad's ``addressLocality`` (city). Only one Dutch
city is seeded in ``ref.cities``, so the ``SOURCE_HOME_COUNTRY`` fallback
(``nationalevacaturebank_nl`` -> ``NL``) is what keeps every other town on the
Netherlands instead of collapsing onto the shared global-remote location.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.qualification_mappers import (
    extract_normalized_benefits,
    extract_normalized_skills,
    extract_seniority_and_management,
    extract_work_schedule,
    map_experience_level,
    map_job_category,
)
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.nationalevacaturebank_nl.models import (
        RawNationaleVacaturebankNlJob,
    )

#: schema.org ``employmentType`` -> ``ref.employment_types.code``.
_EMPLOYMENT_TYPES: dict[str, str] = {
    "full_time": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "part_time": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "contractor": "contract",
    "contract": "contract",
    "temporary": "temporary",
    "intern": "internship",
    "internship": "internship",
    "apprenticeship": "apprenticeship",
    "freelance": "freelance",
}

#: ``credentialCategory`` -> ``ref.education_levels.code``. Ordered
#: most-specific first; Dutch terms are included because the board localises
#: some ads even though the measured sample was English.
_EDUCATION_BY_VALUE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("phd", ("phd", "doctorate", "doctoral", "doctor")),
    ("master", ("master", "wo-master", "universitair", "master's")),
    ("bachelor", ("bachelor", "hbo", "bachelor's")),
    ("associate", ("associate", "mbo")),
    ("high_school", ("high school", "secondary school", "havo", "vwo", "vmbo")),
    ("professional_certification", ("certificate", "certification", "certified")),
)

#: Raw values that mean "no fixed employment type" and must stay unmapped.
_UNMAPPED_EMPLOYMENT_TYPES = {"other", "permanent", "temporary_contract"}


def _map_employment_type(values: list[str]) -> str | None:
    """Map only when the list names exactly one employment type."""
    codes: set[str] = set()
    for value in values or []:
        key = re.sub(r"\s+", " ", str(value).strip().lower())
        if not key or key in _UNMAPPED_EMPLOYMENT_TYPES:
            continue
        code = _EMPLOYMENT_TYPES.get(key)
        if code:
            codes.add(code)
    if len(codes) == 1:
        return codes.pop()
    return None


def _map_education_level(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    for code, needles in _EDUCATION_BY_VALUE:
        if any(needle in text for needle in needles):
            return code
    logger.debug("Unrecognized Nationale Vacaturebank education level {!r}", value)
    return None


def _map_remote_work(value: str | None) -> str | None:
    token = (value or "").strip().upper()
    if token in {"TELECOMMUTE", "TELECOMMUTING", "REMOTE"}:
        return "remote_country"
    return None


def _to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)


def _quality_score(
    *, salary_disclosed: bool, has_location: bool, skills_normalized: str | None, description: str
) -> float:
    signals = [
        salary_disclosed,
        has_location,
        skills_normalized is not None,
        len(description.split()) >= 50,
    ]
    return round(sum(signals) / len(signals), 2)


class NationaleVacaturebankNlCleaner:
    """Turns ``RawNationaleVacaturebankNlJob`` records into ``CleanedJob``."""

    def clean_job(self, raw: RawNationaleVacaturebankNlJob) -> CleanedJob:
        title = clean_plain_text(raw.title) or raw.title
        body = clean_html_text(raw.description_html) or ""
        word_count = len(body.split()) if body else 0
        full_text = "\n\n".join(part for part in (title, body) if part)

        salary_disclosed = raw.salary_min is not None or raw.salary_max is not None
        pay_period = "monthly"
        if salary_disclosed and raw.salary_period:
            pay_period = raw.salary_period

        employment_code = _map_employment_type(raw.employment_types)
        education_code = _map_education_level(raw.education_credential)
        remote_code = _map_remote_work(raw.job_location_type)

        experience_years = round(raw.experience_months / 12, 1) if raw.experience_months else None
        experience_code = map_experience_level(None, title=title, years=experience_years)
        seniority, is_managerial = extract_seniority_and_management(title, body)

        skills_normalized = extract_normalized_skills(full_text)
        benefits_normalized = extract_normalized_benefits(full_text)
        work_schedule = extract_work_schedule(full_text)
        category_code = map_job_category(title, raw.occupational_category or raw.industry)

        location = (raw.location_text or "").strip() or (raw.region or "").strip() or "Netherlands"
        posting_dt = _to_datetime(raw.posted_date)
        closing_dt = _to_datetime(raw.closing_date)
        if posting_dt and closing_dt and closing_dt < posting_dt:
            closing_dt = None

        payload = dict(raw.raw or {})
        payload.update(
            {
                "region": raw.region,
                "postal_code": raw.postal_code,
                "latitude": raw.latitude,
                "longitude": raw.longitude,
                "employment_types": raw.employment_types,
                "work_hours": raw.work_hours,
                "education_credential": raw.education_credential,
                "experience_months": raw.experience_months,
                "occupational_category": raw.occupational_category,
                "industry": raw.industry,
                "job_location_type": raw.job_location_type,
                "direct_apply": raw.direct_apply,
                "salary_published": salary_disclosed,
                "salary_currency": raw.salary_currency,
                "salary_unit_raw": raw.salary_unit_raw,
                "salary_period_assumed": raw.salary_period_assumed,
                "estimated_salary": raw.estimated_salary,
                "listing_category": raw.listing_category,
                "language": "nl",
            }
        )

        return CleanedJob(
            source_job_id=raw.source_job_id,
            job_title=title,
            company_name=clean_plain_text(raw.company_name) or "Unknown employer",
            company_logo_url=raw.company_logo_url or None,
            skills=[],
            location_cleaned=location,
            salary_min=raw.salary_min,
            salary_max=raw.salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=word_count,
            apply_url=raw.job_url,
            original_url=raw.job_url or "",
            posting_date=posting_dt,
            closing_date=closing_dt,
            data_quality_score=_quality_score(
                salary_disclosed=salary_disclosed,
                has_location=bool(raw.location_text and raw.location_text.strip()),
                skills_normalized=skills_normalized,
                description=body,
            ),
            raw_payload=payload,
            currency_iso_code=raw.salary_currency or "EUR",
            pay_period=pay_period,
            employment_type_code=employment_code,
            education_level_code=education_code,
            experience_level_code=experience_code,
            remote_work_type_code=remote_code,
            job_category_code=category_code,
            experience_years_min=int(experience_years) if experience_years is not None else None,
            experience_years_max=None,
            seniority_role_type=seniority,
            is_managerial=is_managerial,
            work_schedule=work_schedule,
            skills_normalized=skills_normalized,
            benefits_normalized=benefits_normalized,
        )

    def clean_jobs(self, jobs: list[RawNationaleVacaturebankNlJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Nationale Vacaturebank ads that could not be cleaned: {}",
                len(failures),
                len(jobs),
                failures[:3],
            )
        if jobs and not cleaned:
            logger.error(
                "every Nationale Vacaturebank ad failed cleaning -- the scraper "
                "would report success while persisting nothing"
            )
        return cleaned

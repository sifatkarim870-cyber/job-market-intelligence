"""Cleans NEA Cambodia raw vacancies into storage-ready ``CleanedJob`` records.

The National Employment Agency publishes no schema.org block, so the parser
already mapped the board's Khmer labels onto typed fields. This cleaner:

* Keeps the salary in **USD, monthly** whenever the board published one. A
  vacancy with no salary text is stored salary-undisclosed in USD with
  ``pay_period="monthly"`` -- the Cambodian convention, and a required column.
* Maps the Board's Khmer employment-type phrase (``ការងារពេញម៉ោង`` =
  full-time) onto ``ref.employment_types``.
* Maps only unambiguous Khmer degree names onto ``ref.education_levels``.
  ``មិនទាន់បញ្ចប់សាកលវិទ្យាល័យ`` ("has not yet finished university") is
  deliberately left unmapped: it describes a candidate, not a completed
  level, and the raw phrase stays in ``raw_payload``.
* Turns "no experience required" (``មិនទាមទារបទពិសោធន៍``) into 0 years, so the
  shared mapper records ``entry``; a numeric ``N ឆ្នាំ`` becomes N years.
* Leaves the remote flag ``None``: the board publishes no remote signal, and
  absence is not a statement that the role is on-site.

``location_cleaned`` is the province from the workplace pair, falling back to
the employer address. Cambodia is seeded but has no cities, so
``SOURCE_HOME_COUNTRY`` (``nea_gov_kh`` -> ``KH``) is what keeps every province
on Cambodia instead of collapsing onto the shared global-remote location.
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
    from job_market_intel.scrapers.nea_gov_kh.models import RawNeaGovKhJob

#: The board's Khmer employment-type phrases -> ``ref.employment_types.code``.
_EMPLOYMENT_TYPES: dict[str, str] = {
    "ការងារពេញម៉ោង": "full_time",
    "full_time": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "ការងារក្រៅម៉ោង": "part_time",
    "part_time": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "ការងារតាមកាលកំណត់": "temporary",
    "temporary": "temporary",
    "កិច្ចសន្យា": "contract",
    "contract": "contract",
    "contractor": "contract",
    "កម្មសិក្សា": "internship",
    "intern": "internship",
    "internship": "internship",
    "ការងារឯករាជ្យ": "freelance",
    "freelance": "freelance",
    "ការងារបណ្តុះបណ្តាល": "apprenticeship",
    "apprenticeship": "apprenticeship",
}

#: Raw values that mean "no fixed employment type" and must stay unmapped.
_UNMAPPED_EMPLOYMENT_TYPES = {"other", "permanent", "temporary_contract"}

#: Unambiguous Khmer degree names -> ``ref.education_levels.code``. Ordered
#: most-specific first: ``អនុបណ្ឌិត`` (master) contains ``បណ្ឌិត`` (phd), and
#: ``បរិញ្ញាបត្ររង`` (associate) contains ``បរិញ្ញាបត្រ`` (bachelor), so the
#: longer term must be tested before the shorter one.
_EDUCATION_BY_VALUE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("master", ("អនុបណ្ឌិត", "បរិញ្ញាបត្រជាន់ខ្ពស់", "master", "master's")),
    ("phd", ("បណ្ឌិត", "phd", "doctorate", "doctoral")),
    ("associate", ("បរិញ្ញាបត្ររង", "associate")),
    ("bachelor", ("បរិញ្ញាបត្រ", "បរិញ្ញាប័ត្រ", "bachelor", "bachelor's")),
    ("high_school", ("វិទ្យាល័យ", "មធ្យមសិក្សា", "high school", "secondary school")),
    (
        "professional_certification",
        ("វិជ្ជាជីវៈ", "បណ្តុះបណ្តាល", "certificate", "certification", "certified"),
    ),
    ("none", ("មិនទាមទារការអប់រំ", "គ្មានការអប់រំ", "no education", "none")),
)

#: Khmer digits -> ASCII digits.
_KH_DIGITS = str.maketrans("០១២៣៤៥៦៧៨៩", "0123456789")

#: Phrases that mean "no experience required".
_NO_EXPERIENCE = ("មិនទាមទារ", "គ្មានបទពិសោធន៍")
_NO_EXPERIENCE_TOKENS = {"ទេ", "no", "none", ""}


def _map_employment_type(values: list[str]) -> str | None:
    """Map only when the list names exactly one employment type."""
    codes: set[str] = set()
    for value in values or []:
        key = re.sub(r"\s+", " ", str(value).strip().lower())
        key = key.replace("\u200b", "")
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
    text = str(value).strip().lower().replace("\u200b", "")
    if not text:
        return None
    for code, needles in _EDUCATION_BY_VALUE:
        if any(needle in text for needle in needles):
            return code
    logger.debug("Unrecognized NEA Cambodia education phrase {!r}", value)
    return None


def _experience_years(value: str | None) -> float | None:
    """Return 0 for "no experience required", or the stated number of years."""
    if not value:
        return None
    text = str(value).strip().replace("\u200b", "")
    lowered = text.lower()
    if lowered in _NO_EXPERIENCE_TOKENS or any(p in text for p in _NO_EXPERIENCE):
        return 0.0
    normalised = text.translate(_KH_DIGITS)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ឆ្នាំ|year|years|yr)", normalised, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)", normalised)
    if match:
        return float(match.group(1))
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


class NeaGovKhCleaner:
    """Turns ``RawNeaGovKhJob`` records into ``CleanedJob``."""

    def clean_job(self, raw: RawNeaGovKhJob) -> CleanedJob:
        title = clean_plain_text(raw.title) or raw.title
        body = clean_html_text(raw.description_html) or ""
        word_count = len(body.split()) if body else 0
        full_text = "\n\n".join(part for part in (title, body) if part)

        salary_disclosed = raw.salary_min is not None or raw.salary_max is not None

        employment_code = _map_employment_type(raw.employment_types)
        education_code = _map_education_level(raw.education_raw)
        experience_years = _experience_years(raw.experience_raw)
        experience_code = map_experience_level(None, title=title, years=experience_years)
        seniority, is_managerial = extract_seniority_and_management(title, body)

        skills_normalized = extract_normalized_skills(full_text)
        benefits_normalized = extract_normalized_benefits(full_text)
        work_schedule = extract_work_schedule(full_text)
        category_code = map_job_category(title, raw.occupational_category or raw.industry)

        location = (raw.location_text or "").strip() or (raw.address or "").strip() or "Cambodia"
        posting_dt = _to_datetime(raw.posted_date)
        closing_dt = _to_datetime(raw.closing_date)
        if posting_dt and closing_dt and closing_dt < posting_dt:
            closing_dt = None

        payload = dict(raw.raw or {})
        payload.update(
            {
                "address": raw.address,
                "region": raw.region,
                "employment_types": raw.employment_types,
                "contract_type_raw": raw.contract_type_raw,
                "education_raw": raw.education_raw,
                "experience_raw": raw.experience_raw,
                "occupational_category": raw.occupational_category,
                "industry": raw.industry,
                "salary_text_raw": raw.salary_text_raw,
                "salary_published": salary_disclosed,
                "salary_currency": raw.salary_currency,
                "vacancies_count": raw.vacancies_count,
                "listing_category": raw.listing_category,
                "language": "km",
            }
        )

        return CleanedJob(
            source_job_id=raw.source_job_id,
            job_title=title,
            company_name=clean_plain_text(raw.company_name) or "Unknown employer",
            company_logo_url=None,
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
            currency_iso_code=raw.salary_currency or "USD",
            pay_period="monthly",
            employment_type_code=employment_code,
            education_level_code=education_code,
            experience_level_code=experience_code,
            remote_work_type_code=None,
            job_category_code=category_code,
            experience_years_min=int(experience_years) if experience_years is not None else None,
            experience_years_max=None,
            seniority_role_type=seniority,
            is_managerial=is_managerial,
            work_schedule=work_schedule,
            skills_normalized=skills_normalized,
            benefits_normalized=benefits_normalized,
        )

    def clean_jobs(self, jobs: list[RawNeaGovKhJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} NEA Cambodia vacancies that could not be cleaned: {}",
                len(failures),
                len(jobs),
                failures[:3],
            )
        if jobs and not cleaned:
            logger.error(
                "every NEA Cambodia vacancy failed cleaning -- the scraper would "
                "report success while persisting nothing"
            )
        return cleaned

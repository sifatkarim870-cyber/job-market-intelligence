"""Cleans raw Karriere.at postings into the shared ``CleanedJob`` contract.

``employmentType`` arrives as a **list** (``[\"PART_TIME\"]``) -- the same shape
as Angola Emprego, not the bare string Jobweb Ghana sends. Both shapes survive
the normaliser.

``Salary`` nests ``value``/``minValue``/``maxValue``/``unitText`` under ``value``
(the Apna/Mustakbil shape) and ``unitText`` is ``\"MONTH\"``, so ``pay_period``
is **monthly** rather than the ``yearly`` default.

Postings are in **German**. ``core.jobs.language_code`` plus the existing
translation kernel handles that; nothing is translated at scrape time.

Austria is supplied by ``SOURCE_HOME_COUNTRY`` because ``addressCountry`` was
not present on the measured postings.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.karriere_at.models import RawKarriereAtJob

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "CONTRACTOR": "freelance",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
    "PERMANENT": "full_time",
    "PER_DIEM": None,
    "OTHER": None,
}

_UNIT_MAP = {
    "HOUR": "hourly",
    "DAY": "daily",
    "WEEK": "weekly",
    "MONTH": "monthly",
    "YEAR": "yearly",
}
ALLOWED_PAY_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly", "yearly"})
_FALLBACK_PAY_PERIOD = "yearly"


def _map_employment_type(value) -> str | None:
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    for raw in items:
        key = re.sub(r"[^A-Z]+", "_", str(raw).strip().upper()).strip("_")
        if key in _EMPLOYMENT_MAP:
            mapped = _EMPLOYMENT_MAP[key]
            if mapped is not None:
                return mapped
    logger.warning("Unrecognized Karriere.at employmentType {!r} -- left None.", value)
    return None


def _map_pay_period(unit_text: str | None) -> str:
    if not unit_text:
        return _FALLBACK_PAY_PERIOD
    mapped = _UNIT_MAP.get(unit_text.strip().upper())
    if mapped and mapped in ALLOWED_PAY_PERIODS:
        return mapped
    return _FALLBACK_PAY_PERIOD


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawKarriereAtJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "employment_type": bool(job.employment_type),
        "url": bool(job.url),
        "salary": job.salary_min is not None or job.salary_max is not None,
    }
    return round(sum(signals.values()) / len(signals), 2)


class KarriereAtCleaner:
    """Turns ``RawKarriereAtJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawKarriereAtJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        salary_min, salary_max = raw_job.salary_min, raw_job.salary_max
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "country_raw": raw_job.country,
                "industry": raw_job.industry,
                "employment_type": raw_job.employment_type,
                "salary_unit_text": raw_job.salary_unit_text,
                "company_url": raw_job.company_url,
                "listing_page": raw_job.listing_page,
                "language": "de",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Austria",
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
            currency_iso_code=raw_job.salary_currency or "EUR",
            pay_period=_map_pay_period(raw_job.salary_unit_text),
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawKarriereAtJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Karriere.at postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Karriere.at posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

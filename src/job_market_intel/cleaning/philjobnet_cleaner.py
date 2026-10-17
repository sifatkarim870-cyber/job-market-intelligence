"""Cleans raw PhilJobNet postings into the shared ``CleanedJob`` contract.

The salary reads ``"not specified"`` on most postings and a single figure
(``"â‚±20,000.00"``) on some. The figure has no stated period, so it is stored
with ``pay_period = monthly`` (the Philippine convention) and that guess is
recorded in ``raw_payload`` so it is auditable rather than silent.

Postings are in **English**.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.philjobnet.models import RawPhilJobNetJob

_EMPLOYMENT_MAP = {
    "PERMANENT": "full_time",
    "PROJECT-BASED": "contract",
    "CONTRACTUAL": "contract",
    "CASUAL": "part_time",
    "SEASONAL": "temporary",
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
}


def _map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning(
        "Unrecognized PhilJobNet employment type {!r} -- left None; the real value is "
        "preserved in raw_payload.",
        value,
    )
    return None


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawPhilJobNetJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "url": bool(job.url),
        "employment_type": bool(job.employment_type),
    }
    return round(sum(signals.values()) / len(signals), 2)


class PhilJobNetCleaner:
    """Turns ``RawPhilJobNetJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawPhilJobNetJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "education_level": raw_job.education_level,
                "employment_type": raw_job.employment_type,
                "salary_text": raw_job.salary_text,
                "salary_published": raw_job.salary_min is not None,
                "salary_period_assumed": raw_job.salary_min is not None,
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Philippines",
            salary_min=raw_job.salary_min,
            salary_max=raw_job.salary_max,
            salary_disclosed=raw_job.salary_min is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=None,
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="PHP",
            # The figure has no stated period; monthly is the Philippine
            # convention and is recorded as an assumption in raw_payload.
            pay_period="monthly" if raw_job.salary_min is not None else "yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawPhilJobNetJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} PhilJobNet postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every PhilJobNet posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

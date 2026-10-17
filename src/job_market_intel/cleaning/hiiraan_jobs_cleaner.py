"""Cleans raw Hiiraan postings into the shared ``CleanedJob`` contract.

No salary, no posting date, no company field. The employer is the organization
named in the background prose, which is not a field, so ``company_name`` stays
"Unknown employer".

Postings are in **English**.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.hiiraan_jobs.models import RawHiiraanJobsJob

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "FULL-TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
    "PERMANENT": "full_time",
}


def _map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning("Unrecognized Hiiraan employment type {!r} -- left None.", value)
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


def _storable_closing_date(job: RawHiiraanJobsJob) -> tuple[datetime | None, bool]:
    """The deadline, but only when it is still open.

    Same shape as the Job in Rwanda guard: ``job_repository`` defaults a NULL
    ``posting_date`` to ``date.today()``, so an expired deadline on an undated
    posting sits before the fabricated posting date and trips
    ``ck_jobs_closing_after_posting``. All five real postings on this board had
    a deadline of 17 August 2026, which is before the run date, so without this
    guard every row would be lost.
    """
    if job.closing_date is None:
        return None, False
    if job.closing_date < date.today():
        return None, True
    return _to_datetime(job.closing_date), False


def _quality_score(job: RawHiiraanJobsJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "employment_type": bool(job.employment_type),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class HiiraanJobsCleaner:
    """Turns ``RawHiiraanJobsJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawHiiraanJobsJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())
        closing, expired = _storable_closing_date(raw_job)

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "department": raw_job.department,
                "position_level": raw_job.position_level,
                "reports_to": raw_job.reports_to,
                "employment_type": raw_job.employment_type,
                "salary_published": False,
                "listing_page": raw_job.listing_page,
                "language": "en",
                "deadline_expired": expired,
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Somalia",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=closing,
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="SOS",
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawHiiraanJobsJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Hiiraan postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Hiiraan posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

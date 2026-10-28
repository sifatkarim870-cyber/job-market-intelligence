"""Cleans raw HTML-scraped postings into the shared ``CleanedJob`` contract."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.html_scraper.models import RawHtmlScraperJob


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def storable_closing_date(posted, closing):
    """Drop a deadline that predates the posting."""
    if closing is None:
        return None
    if posted is not None and closing < posted:
        logger.warning(
            "html_scraper: deadline {} predates posting date {} -- dropped",
            closing,
            posted,
        )
        return None
    return closing


_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "FULLTIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
    "FREELANCE": "freelance",
    "APPRENTICESHIP": "apprenticeship",
}


def map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    import re

    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    return None


class HtmlScraperCleaner:
    """Turns ``RawHtmlScraperJob`` records into ``CleanedJob``.

    Currency and pay period are per-board facts carried by the site config.
    The framework serves boards in dozens of countries, and a hard-coded
    USD/monthly stamped a New Zealand hourly rate as US dollars a month
    (2026-10-28).
    """

    def __init__(self, currency_iso_code: str = "USD", pay_period: str = "monthly") -> None:
        self._currency_iso_code = currency_iso_code
        self._pay_period = pay_period

    def clean_job(self, raw_job: RawHtmlScraperJob) -> CleanedJob:
        body = clean_html_text(raw_job.description) or ""
        company = clean_plain_text(raw_job.company_name) or "Unknown employer"
        location = clean_plain_text(raw_job.location) if raw_job.location else None

        raw = dict(raw_job.raw or {})
        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        salary_disclosed = bool(salary_min is not None or salary_max is not None)

        skills = list(raw.get("skills", []) or [])

        payload = dict(raw)
        payload.update(
            {
                "employment_type": raw_job.employment_type,
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.title) or raw_job.title,
            company_name=company,
            company_logo_url=None,
            skills=skills,
            location_cleaned=location or raw_job.country or "Unknown",
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(
                storable_closing_date(raw_job.posted_date, raw_job.closing_date)
            ),
            data_quality_score=self._quality_score(raw_job, body, skills),
            raw_payload=payload,
            currency_iso_code=self._currency_iso_code,
            pay_period=self._pay_period,
            employment_type_code=map_employment_type(raw_job.employment_type),
        )

    def _quality_score(self, job: RawHtmlScraperJob, description: str, skills: list[str]) -> float:
        signals = {
            "title": bool(job.title and job.title.strip()),
            "employer": bool(job.company_name and job.company_name.strip()),
            "description": len(description) >= 200,
            "posted_date": job.posted_date is not None,
            "location": bool(job.location and job.location.strip()),
            "skills": bool(skills),
            "url": bool(job.url),
        }
        return round(sum(signals.values()) / len(signals), 2)

    def clean_jobs(self, raw_jobs: list[RawHtmlScraperJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} html_scraper postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every html_scraper posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

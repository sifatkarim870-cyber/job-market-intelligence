"""Cleans raw Fiji Sun postings into the shared ``CleanedJob`` contract.

Two facts shape this cleaner, both measured:

* **There is no salary.** ``Salary`` reads ``"T.B.D."`` on every measured
  posting, which is not a figure, so ``salary_disclosed`` is always ``False`` and
  no ``pay_period`` is claimed about a number that does not exist. The verbatim
  string is kept in ``raw_payload["salary_text"]``.

* **The posting date is approximate.** It is derived from a relative phrase
  ("Posted 1 week ago", "Posted 3 days ago") rather than published, so
  ``raw_payload["posted_date_is_derived"]`` is ``True`` and any freshness
  analysis over this source must treat the date as an estimate. The closing date
  is absolute ("Closes 5 November 2026").

``Salary`` and ``Openings`` are recorded verbatim; the employer is extracted
from the card header (the ``<h1>``'s parent text minus the ``<h1>``) rather than
from ``og:title``, which is SITE-wide and would store the site's name as every
job's title.

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
    from job_market_intel.scrapers.fijisun_jobs.models import RawFijiSunJobsJob

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "FULL-TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
}

_COUNTRY_MAP = {"fiji": "FJ", "fj": "FJ"}


def _map_country(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().casefold()
    if key in _COUNTRY_MAP:
        return _COUNTRY_MAP[key]
    return value.strip() if re.fullmatch(r"[A-Z]{2}", value.strip()) else None


def _map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning(
        "Unrecognized Fiji Sun employment type {!r} -- left None; the real value is "
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


def _quality_score(job: RawFijiSunJobsJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location or job.country),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "employment_type": bool(job.employment_type),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class FijiSunJobsCleaner:
    """Turns ``RawFijiSunJobsJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawFijiSunJobsJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "country_raw": raw_job.country,
                "country_iso": _map_country(raw_job.country),
                "employment_type": raw_job.employment_type,
                "category": raw_job.category,
                "salary_text": "T.B.D.",
                "salary_published": False,
                "posted_phrase": raw_job.posted_phrase,
                "posted_date_is_derived": raw_job.posted_date is not None,
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
            location_cleaned=raw_job.location or _map_country(raw_job.country),
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="FJD",
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawFijiSunJobsJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001 - one bad posting must not stop the batch
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Fiji Sun postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Fiji Sun posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

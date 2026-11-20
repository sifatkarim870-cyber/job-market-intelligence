"""Cleans raw L'Express Petites Annonces (Mauritius) ads into ``CleanedJob``.

Ads are written in **French or English** (both observed). The board publishes
no structured salary or employer, so those fields are only set when the ad
states them; nothing is inferred. The salary, when present, is prose in the
body and is assumed **monthly** unless the ad says otherwise -- Mauritius
posts monthly figures (see ``myjob_cleaner`` for the same convention).

A remote-work phrase (``télétravail`` / ``remote`` / ...) is recorded in
``raw_payload`` but does **not** set ``remote_work_type_code``: a classifieds
line saying "remote" never states how remote, so mapping it to
``remote_country``/``remote_global`` would be a guess.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.lexpress_mu.models import RawLexpressMuJob

_JOB_TYPE_MAP = {
    "full-time": "full_time",
    "full time": "full_time",
    "fulltime": "full_time",
    "part-time": "part_time",
    "part time": "part_time",
    "parttime": "part_time",
    "contract": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "freelance": "freelance",
}


def _map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    mapped = _JOB_TYPE_MAP.get(normalized)
    if mapped is None:
        for key, code in _JOB_TYPE_MAP.items():
            if key in normalized:
                return code
        logger.warning(
            "Unrecognized L'Express employment type {!r} -- left None; the real "
            "value is preserved in raw_payload.",
            value,
        )
        return None
    return mapped


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawLexpressMuJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name != "Unknown employer"),
        "location": bool(job.location),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "salary": job.salary_min is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class LexpressMuCleaner:
    """Turns ``RawLexpressMuJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawLexpressMuJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        salary_disclosed = raw_job.salary_min is not None
        pay_period = (raw_job.salary_period or "monthly") if salary_disclosed else "yearly"

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "category": raw_job.category,
                "employment_type": raw_job.employment_type,
                "salary_text": raw_job.salary_text,
                "salary_period": raw_job.salary_period,
                "salary_published": salary_disclosed,
                "reference": raw_job.reference,
                "phone": raw_job.phone,
                "contact_emails": raw_job.contact_emails,
                "remote_phrase": raw_job.remote_phrase,
                "listing_page": raw_job.listing_page,
                "language": "fr/en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Mauritius",
            salary_min=raw_job.salary_min,
            salary_max=raw_job.salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=None,
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="MUR",
            pay_period=pay_period,
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawLexpressMuJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} L'Express ads that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every L'Express ad failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

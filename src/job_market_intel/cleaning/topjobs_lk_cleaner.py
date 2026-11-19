"""Cleans raw TopJobs postings into the shared ``CleanedJob`` contract.

TopJobs is a Sri Lankan board, printed in **English**, with the employer,
both dates and the town on the listing row and the body on the ad page.

What this board does and does not publish (measured 2026-11-20):

  * **No salary field.** One of 75 sampled ads mentioned pay in its body at
    all, and none had a structured figure. ``salary_disclosed`` is therefore
    always ``False`` and the currency/pay-period columns state the board's
    home market (``LKR``/``monthly``) rather than an amount.
  * **Most bodies are images** (71 of 75). An image-only ad keeps its title,
    employer, dates, town and URL; ``description_clean`` is ``None`` and
    ``raw_payload['description_is_image']`` says why. That is an honest
    absence, not a parse failure.
  * ``employment_type`` comes from the ad's ``ad-status`` labels. "Permanent"
    is contract nature rather than hours, so it maps to ``full_time`` only
    when no explicit hours label is present (the parser already prefers
    "Full Time"/"Part Time" when both are shown).
  * "Remote" on its own is **not** mapped to ``remote_work_type_code``: the
    schema wants a restriction level (city/country/region/global) that the
    label does not state. "Onsite" and "Hybrid" are unambiguous and are
    mapped; the raw label is always kept in ``raw_payload``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.topjobs_lk.models import RawTopJobsLkJob

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "FULL-TIME": "full_time",
    "PART_TIME": "part_time",
    "PART-TIME": "part_time",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERNSHIP": "internship",
    "INTERN": "internship",
    "FREELANCE": "freelance",
    "PERMANENT": "full_time",
}

_WORK_MODE_MAP = {
    "ONSITE": "on_site",
    "ON_SITE": "on_site",
    "ON-SITE": "on_site",
    "HYBRID": "hybrid",
}


def map_employment_type(value: str | None) -> str | None:
    """Map an ad-status label ("Full Time") to ``ref.employment_types.code``."""
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning("Unrecognized TopJobs employment type {!r} -- left None.", value)
    return None


def map_work_mode(value: str | None) -> str | None:
    """Map "Onsite"/"Hybrid" to ``ref.remote_work_types.code``.

    "Remote" is deliberately not mapped -- see the module docstring.
    """
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    return _WORK_MODE_MAP.get(key)


def _to_datetime(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def storable_closing_date(posted: date | None, closing: date | None) -> datetime | None:
    """The deadline, dropped when it precedes the posting date.

    ``core.jobs`` carries ``ck_jobs_closing_after_posting``; an inverted pair
    cannot be stored. TopJobs filters its listing to ``jst=OPEN``, so this
    should not bite in practice -- but an ad whose listing still says OPEN a
    day after its deadline must not take the whole row down with it.
    """
    if closing is None:
        return None
    if posted is not None and closing < posted:
        return None
    return _to_datetime(closing)


def _quality_score(job: RawTopJobsLkJob, description: str) -> float:
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


class TopJobsLkCleaner:
    """Turns ``RawTopJobsLkJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawTopJobsLkJob) -> CleanedJob:
        body = clean_html_text(raw_job.description) or ""
        title = clean_plain_text(raw_job.title) or raw_job.title
        company = clean_plain_text(re.sub(r"\s+", " ", (raw_job.company_name or "").strip()))
        location = clean_plain_text(raw_job.location) or "Sri Lanka"

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "headcount": raw_job.headcount,
                "listing_snippet": raw_job.listing_snippet,
                "employment_type": raw_job.employment_type,
                "work_mode": raw_job.work_mode,
                "ad_status_labels": list(raw_job.labels),
                "description_is_image": raw_job.description_is_image,
                "salary_published": False,
                "pay_period_assumption": "monthly (the board publishes no pay period)",
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=location,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=storable_closing_date(raw_job.posted_date, raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="LKR",
            pay_period="monthly",
            employment_type_code=map_employment_type(raw_job.employment_type),
            remote_work_type_code=map_work_mode(raw_job.work_mode),
        )

    def clean_jobs(self, raw_jobs: list[RawTopJobsLkJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} TopJobs postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every TopJobs posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

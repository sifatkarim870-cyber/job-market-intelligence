"""Cleans raw JobSearch.az postings into the shared ``CleanedJob`` contract.

What the cleaner is responsible for here
-----------------------------------------
* **Description** is already scoped by the parser to ``#content_block``, so the
  cleaner only normalises whitespace. Scraping whole-page text instead would
  put the site's filter sidebar into every row.
* **No salary is ever set.** The listing renders a ``li.money`` per card, but
  its figure is injected after the DOM snapshot and reads empty. Inventing one
  from the ``<svg>`` next to it would be the classic "something that looks like
  a value but isn't" trap. ``salary_disclosed`` stays False.
* **No location is invented.** The detail page names cities only in prose.
  ``location_cleaned`` stays at the country so geographic resolution reports
  country-only rather than a guessed city.
* **Closing dates are real but the board has no posting dates on the detail
  page.** A deadline earlier than the posting date would trip
  ``ck_jobs_closing_after_posting``, so a deadline that predates the derived
  posting date is dropped.

Postings are in **Azerbaijani**. ``core.jobs.language_code`` plus the existing
translation kernel handles that; nothing is translated at scrape time.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobsearch_az.models import RawJobSearchAzJob

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "FULLTIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
}


def _map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning("Unrecognized JobSearch.az employment type {!r} -- left None.", value)
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


def storable_closing_date(posted, closing):
    """Drop a deadline that predates the posting.

    The listing label carries no year, so a January posting read in December
    resolves to *this* January -- later than its own deadline. Storing that
    trips ``ck_jobs_closing_after_posting`` and aborts the shared transaction.
    """
    if closing is None:
        return None
    if posted is not None and closing < posted:
        logger.warning(
            "jobsearch_az: deadline {} predates posting date {} -- dropped",
            closing,
            posted,
        )
        return None
    return closing


def _quality_score(job: RawJobSearchAzJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "category": bool(job.industry),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobSearchAzCleaner:
    """Turns ``RawJobSearchAzJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobSearchAzJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "industry": raw_job.industry,
                "employer_industry": raw_job.employer_industry,
                "employment_type": raw_job.employment_type,
                "listing_page": raw_job.listing_page,
                "language": "az",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Azerbaijan",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(
                storable_closing_date(raw_job.posted_date, raw_job.closing_date)
            ),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="AZN",
            pay_period="monthly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawJobSearchAzJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} JobSearch.az postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every JobSearch.az posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

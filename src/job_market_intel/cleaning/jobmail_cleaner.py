"""Cleans raw JobMail postings into the shared ``CleanedJob`` contract.

What the cleaner is responsible for
-----------------------------------
* **"Market Related" is a salary that is not a figure.** The board publishes
  one in the same field as the amounts, and it is kept as
  ``salary_undisclosed`` rather than turned into a number.
* **The currency is ZAR and the cadence is monthly** when a figure is
  published, and both come from the record -- the detail page's
  ``baseSalary.unitText`` where it has one, the card's "PER MONTH" otherwise.
* **The location is "town, province"**, the form the geographic resolver can
  act on. The board's granularity varies -- a city on some postings, a
  province on others -- and both are in the corpus's South African reference
  data.
* **A deadline that predates the posting is dropped**, because
  ``ck_jobs_closing_after_posting`` would otherwise abort the shared
  transaction and take every later row with it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobmail.models import RawJobMailJob

#: The country for a posting whose JSON-LD gave no addressCountry. The board
#: is South African, so this is the fallback, never the primary.
_DEFAULT_COUNTRY = "ZA"


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
    """Drop a deadline that predates the posting (same guard as the other sources)."""
    if closing is None:
        return None
    if posted is not None and closing < posted:
        logger.warning("jobmail: deadline %s predates posting date %s -- dropped", closing, posted)
        return None
    return closing


def _quality_score(job: RawJobMailJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "location": bool(job.location),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobMailCleaner:
    """Turns ``RawJobMailJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobMailJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        body = re.sub(r"[ \t]{2,}", " ", body).strip()
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "industry": raw_job.industry,
                "salary_undisclosed": raw_job.salary_undisclosed,
                "card_location": raw_job.raw.get("card_location") if raw_job.raw else None,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or raw_job.country or _DEFAULT_COUNTRY,
            salary_min=raw_job.salary_min,
            salary_max=raw_job.salary_max,
            salary_disclosed=bool(raw_job.salary_min is not None or raw_job.salary_max is not None),
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
            currency_iso_code=raw_job.salary_currency or "ZAR",
            pay_period=raw_job.pay_period or "monthly",
            employment_type_code=raw_job.employment_type_code,
        )

    def clean_jobs(self, raw_jobs: list[RawJobMailJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} jobmail postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every jobmail posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

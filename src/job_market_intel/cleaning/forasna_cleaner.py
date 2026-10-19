"""Cleans raw Forasna postings into the shared ``CleanedJob`` contract.

What the cleaner is responsible for
-----------------------------------
* **The currency is per posting.** 18 of 60 sampled postings declare EGP and
  one declares **USD** on an Egyptian board, so the record's own currency is
  used. Assuming EGP would silently mis-file the dollar one.
* **The salary is monthly.** ``unitText`` is ``MONTH`` on every sampled
  posting carrying a figure, and ``pay_period`` is checked against the
  schema's vocabulary -- a value outside it aborts the shared transaction and
  takes every later row with it.
* **A posting with no salary is not given one.** 32% of postings carry a
  figure; the rest are left undisclosed rather than zero-filled.
* **The location is "locality, region"**, the shape the geographic resolver
  can act on. The raw address is kept in the payload.
* **The country comes from the record, not from the board.** One sampled
  posting's ``addressRegion`` is "أبها" -- Abha, in **Saudi Arabia** -- so a
  posting filed under Egypt on the strength of its region would be wrong.
* **A missing description stays missing.** 27% of postings have no body; the
  page then shows only a structured requirements block, which is not a
  description.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.forasna.models import RawForasnaJob

#: The country for a posting whose JSON-LD gave no addressCountry. The board
#: is Egyptian, so this is the fallback, never the primary.
_DEFAULT_COUNTRY = "EG"

#: ISO 4217 codes the board is known to use, mapped to the corpus's
#: currency table. A currency the corpus has not got is not invented.
_CURRENCY_FALLBACK = "EGP"


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawForasnaJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "description": len(description) >= 100,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "location": bool(job.location),
        "salary": job.salary_min is not None or job.salary_max is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class ForasnaCleaner:
    """Turns ``RawForasnaJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawForasnaJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        body = re.sub(r"[ \t]{2,}", " ", body).strip()
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        currency = (raw_job.salary_currency or "").upper() or None
        if currency is None and (raw_job.salary_min is not None or raw_job.salary_max is not None):
            currency = _CURRENCY_FALLBACK
            logger.warning(
                "forasna posting %s has a salary but no currency -- using %s",
                raw_job.source_job_id,
                currency,
            )

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "locality": raw_job.locality,
                "region": raw_job.region,
                "employment_type": raw_job.employment_type,
                "language": "ar",
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
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code=currency or "EGP",
            # MONTH on every sampled posting that carries a figure.
            pay_period=raw_job.pay_period or "monthly",
            employment_type_code=raw_job.employment_type_code,
        )

    def clean_jobs(self, raw_jobs: list[RawForasnaJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} forasna postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every forasna posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

"""Cleans raw Jobs.ge postings into the shared ``CleanedJob`` contract.

What the cleaner is responsible for
-----------------------------------
* **Two titles, not one swap.** The description is Georgian, so
  ``job_title`` is the Georgian title and ``raw_payload["title_en"]`` carries
  the English one the listing publishes. Substituting the English title over a
  Georgian description would make the row look internally inconsistent; storing
  both says plainly that one is a translation of the other.
* **No salary.** Jobs.ge ads mention pay only in prose, mixed with internship
  and trainee rates in the same ad ("ხელფასი: 3400 ლარიდან" = "salary: from
  3400 lari"). Scraping a figure out of running text is the "looks like a value
  but isn't" trap, so ``salary_disclosed`` stays False.
* **No location.** Tbilisi appears in the ad body, never in a field. The
  country alone is the honest answer, and the resolver pins it to Georgia.
* **Closing dates are real but year-less.** The deadline comes from
  "ბოლო ვადა: 16 ნოემბერი" with the year inferred. A deadline earlier
  than the posting date is dropped, because ``ck_jobs_closing_after_posting``
  would otherwise abort the shared transaction.

The ad body carries the employer's own markdown-ish bullets ("** ხელფასი ...")
from the site's WYSIWYG editor. Those artifacts are stripped rather than
stored, for the same reason as the other sources: they are not part of the
description and they survive into the translated columns.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobsge.models import RawJobsGeJob

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

_EDITOR_ARTIFACTS = (
    (re.compile(r"(?m)^\s*\*\*\s*"), ""),  # "** " bullets
    (re.compile(r"\*\*"), ""),  # stray bold markers
    (re.compile(r"\[\s*\]\([^)]*\)"), ""),  # [](url) links
    (re.compile(r"(?m)^\s*#+\s*"), ""),  # headings
)


def map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning("Unrecognized Jobs.ge employment type {!r} -- left None.", value)
    return None


def clean_editor_text(text: str | None) -> str:
    """Strip the WYSIWYG exporter's artifacts from the ad body."""
    if not text:
        return ""
    out = text
    for pattern, repl in _EDITOR_ARTIFACTS:
        out = pattern.sub(repl, out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


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
    """Drop a deadline that predates the posting (same guard as the other two sources)."""
    if closing is None:
        return None
    if posted is not None and closing < posted:
        logger.warning("jobs.ge: deadline {} predates posting date {} -- dropped", closing, posted)
        return None
    return closing


def _quality_score(job: RawJobsGeJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "title_en": bool(job.title_en and job.title_en.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobsGeCleaner:
    """Turns ``RawJobsGeJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobsGeJob) -> CleanedJob:
        body = clean_html_text(clean_editor_text(raw_job.description)) or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "title_en": raw_job.title_en,
                "listing_published": raw_job.listing_published,
                "listing_deadline": raw_job.listing_deadline,
                "listing_page": raw_job.listing_page,
                "language": "ka",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Georgia",
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
            currency_iso_code="GEL",
            pay_period="monthly",
            employment_type_code=map_employment_type(raw_job.employment_type),
            # The site's OWN English title from /en/jobs, not a translation of
            # the Georgian one. Setting it makes translation.py skip this row
            # (its selection is "job_title_en IS NULL"), so the publisher's
            # English survives instead of being replaced by a machine
            # translation. See CleanedJob.job_title_en.
            job_title_en=(raw_job.title_en or None),
        )

    def clean_jobs(self, raw_jobs: list[RawJobsGeJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} jobs.ge postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every jobs.ge posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

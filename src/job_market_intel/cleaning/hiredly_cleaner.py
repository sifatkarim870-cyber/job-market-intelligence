"""Cleans raw Hiredly postings into the shared ``CleanedJob`` contract.

What the cleaner is responsible for
-----------------------------------
* **Salary.** ``structuredJobData.baseSalary.value`` carries the figures and
  ``unitText: "MONTH"`` the period. ``MONTH`` maps to ``monthly``; anything
  else is left ``None`` rather than guessed, because ``pay_period`` is a CHECK
  constraint and a wrong value aborts the shared transaction and fails every
  later row in the batch. When the employer published nothing, the posting's
  display string reads ``"Undisclosed"`` and ``salary_disclosed`` stays False --
  that word is never parsed for digits.
* **Description.** The site exports its WYSIWYG body as markdown-ish text:
  bullet underscores (``_ TWO Slots Open``), ``**bold**``, ``<br>``. The
  exporter's artifacts are stripped rather than stored, because they are not
  part of the job description and they survive into the translated columns.
* **Location.** ``location`` and ``stateRegion`` are both published, so the
  value is real rather than inferred: "Petaling Jaya, Selangor".
* **Closing date.** ``validThrough`` is present on most postings and is a real
  deadline. A deadline earlier than the posting date is dropped, because
  ``ck_jobs_closing_after_posting`` would otherwise abort the batch.

Postings are in **English**. The board is English-only for these employers, so
``core.jobs.language_code`` is left to the translation kernel rather than
guessed here.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.hiredly.models import RawHiredlyJob

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

#: schema.org ``unitText`` -> this project's ``pay_period`` vocabulary. Only
#: MONTH has been observed; an unlisted value is dropped rather than assumed.
_PAY_PERIOD_BY_UNIT = {"MONTH": "monthly"}

#: The WYSIWYG exporter's leftovers.
_EDITOR_ARTIFACTS = (
    (re.compile(r"(?m)^\s*[-*]\s+"), ""),  # "- " bullets
    (re.compile(r"(?m)^\s*_\s+"), ""),  # "_ " bullets
    (re.compile(r"\*\*([^*]{1,200})\*\*"), r"\1"),  # **bold**
    (re.compile(r"(?m)^\s*#+\s*"), ""),  # headings
    (re.compile(r"\[\s*\]\([^)]*\)"), ""),  # [](url) links
)


def map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning("Unrecognized Hiredly employment type {!r} -- left None.", value)
    return None


def map_pay_period(unit_text: str | None) -> str | None:
    """``"MONTH"`` -> ``"monthly"``. Unmapped values stay None on purpose."""
    if not unit_text:
        return None
    mapped = _PAY_PERIOD_BY_UNIT.get(unit_text.strip().upper())
    if mapped is None:
        logger.warning(
            "Unrecognized Hiredly salary unitText {!r} -- pay_period left None "
            "rather than guessed.",
            unit_text,
        )
    return mapped


def clean_editor_text(text: str | None) -> str:
    """Strip the rich-text exporter's artifacts from the description."""
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
    """Drop a deadline that predates the posting (same guard as jobsearch_az)."""
    if closing is None:
        return None
    if posted is not None and closing < posted:
        logger.warning("hiredly: deadline {} predates posting date {} -- dropped", closing, posted)
        return None
    return closing


def _quality_score(job: RawHiredlyJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "salary": job.salary_min is not None,
        "category": bool(job.job_category),
    }
    return round(sum(signals.values()) / len(signals), 2)


class HiredlyCleaner:
    """Turns ``RawHiredlyJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawHiredlyJob) -> CleanedJob:
        body = clean_html_text(clean_editor_text(raw_job.description)) or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())
        requirements = clean_editor_text(raw_job.requirements) or None

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "job_category": raw_job.job_category,
                "skills": raw_job.skills,
                "min_years_experience": raw_job.min_years_experience,
                "max_years_experience": raw_job.max_years_experience,
                "employer_industry": raw_job.company_industry,
                "requirements": requirements,
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            skills=list(raw_job.skills or []),
            location_cleaned=raw_job.location or "Malaysia",
            salary_min=raw_job.salary_min,
            salary_max=raw_job.salary_max,
            salary_disclosed=raw_job.salary_min is not None,
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
            currency_iso_code=raw_job.salary_currency or "MYR",
            # A posting with no published salary has no period either. `None`
            # would fail the CHECK constraint, so the column's one safe value
            # is used and `salary_disclosed=False` carries the truth.
            pay_period=map_pay_period(raw_job.salary_unit_text) or "monthly",
            employment_type_code=map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawHiredlyJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Hiredly postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Hiredly posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

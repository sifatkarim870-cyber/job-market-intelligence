"""Cleans raw JobsIreland.ie postings into the shared ``CleanedJob`` contract.

What the cleaner is responsible for
-----------------------------------
* **The listing title is not the title.** ``JobTitle`` is
  ``"Caretaker of Sports Ground (Elton) - CE Scheme - SLIABH RI LIMITED"``. The
  employer is lifted out and dropped from the title; the detail page's ``<h3>``
  already has both properties and is preferred.
* **The address is reduced, not stored raw.** ``location_cleaned`` gets
  ``"town, county"``. The full mailing address is kept in ``raw_payload`` so
  nothing is lost. Measured: 1 of 16 real addresses resolved before the
  reduction, 16 of 16 after.
* **There is no salary.** The euro icon on the detail page sits beside the
  *label* of a link to a programme-wide rates page -- "Community Employment
  Programme Rates" -- with no figure anywhere. ``salary_disclosed`` stays
  False and no number is derived from it.
* **A deadline that predates the posting is dropped**, because
  ``ck_jobs_closing_after_posting`` would otherwise abort the shared
  transaction and take every later row with it.
* **The vacancy type maps to an employment type**, from the site's own
  ``#VacancyTypeId`` select: 0 Paid Position -> full_time, 3 CE Scheme ->
  part_time, 4 Apprenticeship -> apprenticeship, 6 Self Employed -> freelance,
  10 WPEP -> internship.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobsireland.models import RawJobsIrelandJob

from job_market_intel.scrapers.jobsireland.models import VACANCY_TYPES

#: VacancyTypeId -> employment_type_code. Read off the #VacancyTypeId select
#: rather than guessed; -1 ("All") has no type and is left None.
_VACANCY_TO_EMPLOYMENT = {key: employment for key, (_label, employment) in VACANCY_TYPES.items()}

#: Residual junk the page's markup leaves behind.
_STRIP_PATTERNS = (
    (re.compile(r"\bImage for \w+\b"), ""),  # alt text leaking into the text run
    (re.compile(r"^\s*Ref:\s*\S+\s*$", re.M), ""),
    (re.compile(r"href=\"[^\"]*\""), ""),
    (re.compile(r"<[^>]+>"), " "),
)


def strip_artifact_lines(text: str | None) -> str:
    """Remove the debris the raw text run picks up; keep the prose."""
    if not text:
        return ""
    out = text
    for pattern, repl in _STRIP_PATTERNS:
        out = pattern.sub(repl, out)
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in out.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def vacancy_employment_type(vacancy_type_id: str | None) -> str | None:
    """Map ``VacancyTypeId`` onto ``ref.employment_types.code``."""
    if not vacancy_type_id:
        return None
    code = _VACANCY_TO_EMPLOYMENT.get(vacancy_type_id)
    if code is None and vacancy_type_id != "-1":
        logger.warning("Unrecognized JobsIreland VacancyTypeId {!r} -- left None.", vacancy_type_id)
    return code


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
        logger.warning(
            "jobsireland.ie: deadline %s predates posting date %s -- dropped",
            closing,
            posted,
        )
        return None
    return closing


def _quality_score(job: RawJobsIrelandJob, description: str) -> float:
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "description": len(description) >= 400,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "location": bool(job.location_reduced),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobsIrelandCleaner:
    """Turns ``RawJobsIrelandJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobsIrelandJob) -> CleanedJob:
        body = strip_artifact_lines(clean_html_text(raw_job.description or "")) or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "listing_title": raw_job.listing_title,
                "reference": raw_job.reference,
                "positions": raw_job.positions,
                "hours_per_week": raw_job.hours_per_week,
                "vacancy_type_id": raw_job.vacancy_type_id,
                "vacancy_type_label": raw_job.vacancy_type_label,
                "address_raw": raw_job.location,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url or None,
            skills=[],
            location_cleaned=raw_job.location_reduced or raw_job.location,
            salary_min=None,
            salary_max=None,
            # The euro icon labels a link to a programme-wide rates page; there
            # is no figure anywhere on the page.
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
            currency_iso_code="EUR",
            pay_period="hourly",
            employment_type_code=vacancy_employment_type(raw_job.vacancy_type_id),
        )

    def clean_jobs(self, raw_jobs: list[RawJobsIrelandJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} jobsireland.ie postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every jobsireland.ie posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

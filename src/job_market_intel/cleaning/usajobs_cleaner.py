"""Cleans raw USAJOBS postings into the shared ``CleanedJob`` contract.

Three things are specific to the federal board:

* **Titles are shouted.** Every posting is ALL CAPS ("GENERAL ENGINEER"), which
  wrecks any case-insensitive title matching downstream -- the same role is
  "General Engineer" at one agency and "GENERAL ENGINEER" at another. They are
  title-cased here, but only when the title is *entirely* upper case, so an
  acronym-bearing title ("GS-15 IT Specialist (NETP)") survives intact.
* **The employer is the agency, and it repeats.** ``OrganizationName`` is a
  bureau ("U.S. Army Corps of Engineers") nested inside ``DepartmentName``
  ("Department of the Army") inside a sub-agency. Only the bureau is stored,
  because ``core.companies`` exists to unify employers and a three-level
  government hierarchy would produce a distinct entity per spelling.
* **Pay grades are not salary.** A posting can name a grade (GS-11) and a
  series (0801) without ever stating a figure. Those are kept in the payload
  for analysis but are not treated as a disclosed salary, because "salary
  disclosed" has to mean a number is actually present.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.usajobs.models import RawUSAJobsJob

#: Page furniture carried by every USAJOBS posting, plus the labels that
#: introduce each page section (kept in the description, stripped elsewhere).
_BOILERPLATE = (
    "learn more about this agency",
    "apply",
    "print",
    "share",
    "save",
    "back to results",
    "search results",
    "similar jobs",
)

#: Tokens that must survive title-casing. An explicit allowlist, not a shape
#: like ``[A-Z]{2,}``: in an ALL-CAPS title there is no way to tell "IT" (an
#: acronym) from "NURSE" (a shouted word) by shape alone, and a shape-based
#: rule matches every word -- which silently disables the whole normalisation.
#: Measured on live postings: GS-n pay grades, IT, CY (cyber), RF, the four-digit
#: job-series codes (0801, 0301) and agency abbreviations are what appear.
_ACRONYM = re.compile(
    r"\b(?:IT|GS|WG|SES|CY|RF|PN|DA|VA|USDA|EPA|NASA|FAA|NGA|DHS|DOD|DOJ|VHA|CDC|NIH"
    r"|FDA|FCC|FBI|CIA|NPS|IRS|OPM|GIS|SOCO|NSEP|CAPE)\b"
    r"|\bGS-\d{1,2}\b"  # pay grade, e.g. GS-11
    r"|\b\d{4}\b"  # job series, e.g. 0801
)


def _fix_title(title: str) -> str:
    """Title-case an ALL-CAPS federal title without destroying acronyms."""
    t = (title or "").strip()
    if not t or t != t.upper():
        return t
    protected: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    t = _ACRONYM.sub(_stash, t).title()
    # \x00 is a word boundary for str.title(), so the placeholders survive it.
    for index, original in enumerate(protected):
        t = t.replace(f"\x00{index}\x00", original)
    return re.sub(r"\s+", " ", t).strip()


def _strip_boilerplate(body: str | None) -> str:
    """Drop repeated navigation lines, unescape entities, keep the posting."""
    if not body:
        return ""
    kept = [
        line.strip()
        for line in body.split("\n")
        if line.strip() and line.strip().lower() not in _BOILERPLATE
    ]
    return clean_html_text(html.unescape("\n".join(kept))) or ""


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawUSAJobsJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.organization_name and job.organization_name.strip()),
        "location": bool(job.location_display and job.location_display.strip()),
        "description": len(description) >= 200,
        "salary": job.salary_min is not None,
        "posted_date": job.posted_date is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class USAJobsCleaner:
    """Turns ``RawUSAJobsJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawUSAJobsJob) -> CleanedJob:
        """Clean one posting.

        The description merges the page sections and the API's
        ``QualificationSummary``. They overlap -- both restate "who may apply"
        -- so the summary is dropped when the page sections already cover it,
        which they do for every posting measured on 2026-10-14 (10/10). The
        summary is kept as a fallback for the case where the page fetch failed.
        """
        body = _strip_boilerplate(raw_job.description)
        if len(body) < 200 and raw_job.qualification_summary:
            body = _strip_boilerplate(raw_job.qualification_summary)

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_max is not None and salary_min is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        location = (raw_job.location_display or "").strip()
        if not location and raw_job.city_name:
            location = f"{raw_job.city_name}, {raw_job.state_code}".strip(", ")

        # Grade and series are analysis-relevant but are not a disclosed figure,
        # so they ride in the payload rather than in the salary columns.
        # NOTE: ``raw_payload`` is NOT written by JobRepository.save_cleaned_job
        # -- there is no column for it. Grade, series and the coordinate pair
        # therefore do not reach the database today. They are kept here because
        # they are free to retain, and this is where they will live if the
        # columns are ever added. Do not treat a payload assertion as proof the
        # value is in the corpus: verify against core.jobs.
        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "job_grade": raw_job.job_grade,
                "job_category": raw_job.job_category,
                "department_name": raw_job.department_name,
                "sub_agency": raw_job.sub_agency,
                "schedule_code": raw_job.schedule_code,
                "employment_type": raw_job.employment_type,
                "education_requirements": raw_job.education_requirements,
                "search_keyword": raw_job.search_keyword,
                "country": raw_job.country_code,
                "city": raw_job.city_name,
                "state": raw_job.state_code,
                "latitude": raw_job.latitude,
                "longitude": raw_job.longitude,
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=_fix_title(raw_job.title),
            company_name=(raw_job.organization_name or "").strip() or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=location or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_min is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.apply_url or raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            # Federal salaries are USD, always -- there is no foreign posting on
            # a USAJOBS board, so this is not a guess.
            currency_iso_code="USD",
            # Mapped from the API's RateIntervalCode in the parser, so it is
            # already one of the five values ck_job_salaries_pay_period admits.
            # The fallback matters: a bad value here aborts the enclosing
            # transaction and every later row fails with InFailedSqlTransaction.
            pay_period=raw_job.salary_period or "yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawUSAJobsJob]) -> list[CleanedJob]:
        """Clean a batch, logging failures instead of silently dropping them.

        A silent-empty result has bitten this project in four places now (the
        Job Bank cleaner, the API probes, the Greenhouse walk, the country
        resolver), so an empty return is always explained.
        """
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001 - one bad posting must not stop the batch
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} USAJOBS postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every USAJOBS posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

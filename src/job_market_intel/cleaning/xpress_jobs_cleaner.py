"""Cleans raw XpressJobs postings into the shared ``CleanedJob`` contract.

XpressJobs is a Sri Lankan board, printed in **English**, whose whole ad
body, employer and both dates come from its keyless JSON API.

What this board does and does not publish (measured 2026-11-28):

* **Salary is mostly undisclosed.** The board answers ``minSalary``/
  ``maxSalary`` with the literal ``"Any"`` on most ads, and writes a
  placeholder bound of ``1`` where it hides a figure; those are both
  treated as "not stated" (``salary_disclosed`` False) rather than
  storing a 1-LKR salary. A real whole-LKR amount passes through, and
  currency/pay-period state the board's home market (``LKR``/``monthly``).
* **The body is one HTML blob** (``jobInfo``); it is cleaned into
  ``description_clean``.
* ``employment_type`` comes from ``jobType`` -- observed as
  ``"Full-Time"``, ``"Permanent"`` and ``"Contract Basis"``.
* **No skills list.** ``sectors`` are job categories, not skills, so they
  stay in ``raw_payload`` (under ``sectors``) and ``skills`` is empty --
  an honest absence. The remote flag is a bare boolean with no
  restriction level, so ``remote_work_type_code`` is left None (the
  TopJobs precedent) and the flag is kept in ``raw_payload``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.xpress_jobs.models import RawXpressJob

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``jobType`` -> ref.employment_types.code. Observed live: "Full-Time",
#: "Permanent" and "Contract Basis". The rest are included defensively.
_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "FULL-TIME": "full_time",
    "PERMANENT": "full_time",
    "PART_TIME": "part_time",
    "PART-TIME": "part_time",
    "CONTRACT": "contract",
    "CONTRACT_BASIS": "contract",
    "TEMPORARY": "temporary",
    "INTERNSHIP": "internship",
    "INTERN": "internship",
    "FREELANCE": "freelance",
    "APPRENTICESHIP": "apprenticeship",
}

#: Observed ``jobType`` values that are genuinely unmappable -- "Other"
#: says nothing, and "Full-Time or Part-Time" is two types at once -- so
#: they are recognized only to skip the "unrecognized" warning. The raw
#: value is always preserved in ``raw_payload``.
_NON_MAPPABLE_TYPES = {"OTHER", "FULL_TIME_OR_PART_TIME", "ANY"}


def map_employment_type(value: str | None) -> str | None:
    """Map a ``jobType`` label ("Full-Time") to ``ref.employment_types.code``."""
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    if key in _NON_MAPPABLE_TYPES:
        return None
    logger.warning("Unrecognized XpressJobs employment type {!r} -- left None.", value)
    return None


def _positive(value: int | None) -> int | None:
    """A positive bound passes through; 0/negative means "unstated" -> None."""
    if value is None:
        return None
    return int(value) if int(value) > 0 else None


def _to_datetime(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def storable_closing_date(posted: datetime | None, closing: datetime | None) -> datetime | None:
    """The deadline, dropped when it precedes the posting date.

    ``core.jobs`` carries ``ck_jobs_closing_after_posting``; an inverted
    pair cannot be stored. The board keeps an ad up until its deadline, so
    this should not bite in practice -- but an ad whose ``expiryDateOnSite``
    has already passed must not take the whole row down with it.
    """
    if closing is None:
        return None
    if posted is not None and closing < posted:
        return None
    return closing


def _map_remote(is_remote: bool) -> str | None:
    """The board's bare ``remote`` boolean has no restriction level -> None.

    ``ref.remote_work_types`` wants a city/country/region/global level the
    flag does not state (the TopJobs precedent); the raw flag is preserved
    in ``raw_payload``.
    """
    return None


def _quality_score(job: RawXpressJob, description: str) -> float:
    signals = {
        "title": bool(job.job_title and job.job_title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location_text),
        "description": len(description.split()) >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
        "salary": job.salary_min_raw is not None or job.salary_max_raw is not None,
        "posted_date": job.posting_date is not None,
        "closing_date": job.closing_date is not None,
        "employment_type": bool(job.employment_type_raw),
    }
    return round(sum(signals.values()) / len(signals), 2)


class XpressJobsCleaner:
    """Turns ``RawXpressJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawXpressJob) -> CleanedJob:
        body = clean_html_text(raw_job.description_html) or ""
        title = clean_plain_text(raw_job.job_title) or raw_job.job_title
        company = clean_plain_text(re.sub(r"\s+", " ", (raw_job.company_name or "").strip()))
        location = clean_plain_text(raw_job.location_text) or "Sri Lanka"

        salary_min = _positive(raw_job.salary_min_raw)
        salary_max = _positive(raw_job.salary_max_raw)
        # Reversed bounds come back occasionally (site data error); swap
        # rather than drop -- the same rule every other cleaner applies.
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            logger.warning(
                "XpressJobs job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        salary_disclosed = salary_min is not None or salary_max is not None

        payload = dict(raw_job.raw_payload)
        payload.update(
            {
                "is_remote": raw_job.is_remote,
                "pay_period_assumption": "monthly (the board publishes no pay period)",
                "salary_hidden_placeholders": ["Any", "1"],
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            skills=[],
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=_to_datetime(raw_job.posting_date),
            closing_date=storable_closing_date(raw_job.posting_date, raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="LKR",
            pay_period="monthly",
            employment_type_code=map_employment_type(raw_job.employment_type_raw),
            remote_work_type_code=_map_remote(raw_job.is_remote),
        )

    def clean_jobs(self, raw_jobs: list[RawXpressJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning XpressJobs job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "XpressJobs cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs

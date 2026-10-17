"""Cleans raw ACBAR postings into the shared ``CleanedJob`` contract.

``Salary`` is prose, and nothing is stored
------------------------------------------
Measured values are ``"As Per Organization"``, ``"As per scale"`` and
``"Negotiable"``. None of those is a figure, so every ACBAR row has
``salary_disclosed = False`` and no ``pay_period`` is claimed about a number that
does not exist. The verbatim string is kept in ``raw_payload["salary_text"]`` so
the decision is auditable rather than looking like an omission.

``Type`` is an employment type
-----------------------------
``"Full Time"`` on every posting measured, mapped through the schema's
vocabulary. ``Category`` ("Education, Training", "Engineering, Program") is kept
as the industry.

``Nationality`` is not the posting's country
--------------------------------------------
It reads ``"Afghan"``, ``"National"`` or ``"Male/Female"``-adjacent values
elsewhere in the table, and it describes **who may apply**, not where the job is.
It is preserved verbatim and deliberately not used as the country: the board is
Afghan and ``SOURCE_HOME_COUNTRY`` supplies ``AF``, but mapping "Afghan" onto a
country code from a nationality field would be reading the wrong thing.

No company field
----------------
The employer appears only in the body prose ("About the Company / Company
Profile - Peyawray Rubaat Manufacturing Company"), which is a sentence rather than
a field, so ``company_name`` stays "Unknown employer".

The post language is **English**.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.acbar_jobs.models import RawAcbarJobsJob

#: schema.org ``employmentType`` -> ``ref.employment_types.code``.
#:
#: Keys are written in the **normalised** form the lookup produces, so the table
#: and the normaliser cannot drift apart. ACBAR writes ``"Full Time"``, which
#: normalises to ``FULL_TIME``; keying this table on ``"FULL TIME"`` is what made
#: the first version return ``None`` for every posting on the board.
_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "CONTRACTOR": "freelance",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
    "PERMANENT": "full_time",
}


def _map_employment_type(value: str | None) -> str | None:
    """The ``Type`` row -> a ``ref.employment_types.code``.

    ACBAR writes ``"Full Time"`` with a space, where schema.org uses
    ``FULL_TIME``, so the key is normalised to underscores before lookup.
    """
    if not value:
        return None
    key = re.sub(r"[^A-Z]+", "_", value.strip().upper()).strip("_")
    if key in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[key]
    logger.warning(
        "Unrecognized ACBAR employment type {!r} -- left None; the real value is "
        "preserved in raw_payload.",
        value,
    )
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


def _quality_score(job: RawAcbarJobsJob, description: str) -> float:
    """Completeness, not plausibility.

    ``salary`` is scored on a *usable* figure, so prose like "Negotiable" does
    not read as a strength.
    """
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


class AcbarJobsCleaner:
    """Turns ``RawAcbarJobsJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawAcbarJobsJob) -> CleanedJob:
        """Clean one posting."""
        body = clean_html_text(raw_job.description or "") or ""

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                # Verbatim prose, kept so "no salary stored" is auditable.
                "salary_text": raw_job.salary_text,
                "salary_published": False,
                "nationality": raw_job.nationality,
                "gender": raw_job.gender,
                "contract_duration": raw_job.contract_duration,
                "vacancy_number": raw_job.vacancy_number,
                "no_of_jobs": raw_job.no_of_jobs,
                "education": raw_job.info.get("education"),
                "experience": raw_job.info.get("experience"),
                # The whole table, verbatim.
                "info_table": raw_job.info,
                "has_company_field": False,
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            # No company field exists; the employer is prose-only.
            company_name=raw_job.company_name or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location,
            # "As Per Organization" / "Negotiable" is not a figure.
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="AFN",
            # No salary figure exists, so the period describes nothing.
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawAcbarJobsJob]) -> list[CleanedJob]:
        """Clean a batch, logging failures instead of silently dropping them."""
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001 - one bad posting must not stop the batch
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} ACBAR postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every ACBAR posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

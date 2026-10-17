"""Cleans raw Jobweb Ghana postings into the shared ``CleanedJob`` contract.

The salary is rejected, and that is the most important thing in this file
----------------------------------------------------------------------
**5 of 5 measured postings carry a byte-identical** ``baseSalary``::

    {"currency": "GHS",
     "value": {"value": "1500", "minValue": "1500", "maxValue": "8000",
               "unitText": "MONTH"}}

The five span a Chief Executive Officer, a CCTV Controller and an Accounts
Clerk. Those roles do not share a salary band, and the redundant ``value``
duplicating ``minValue`` is the signature of a site template rather than a
posted figure.

Storing it would put the same invented 1500-8000 GHS band on **every** Ghanaian
row, and it would do so inside a well-formed schema.org block -- so nothing
downstream would flag it. Every salary statistic computed over Ghana would be
quietly wrong, and wrong in the most believable direction possible: a plausible
number in the right currency in the right period.

So the figure is recorded in ``raw_payload`` for audit and **not** stored, which
is the same treatment CareerJunction's ``"R Undisclosed"`` gets. The test that
pins this asserts the salary is absent, so a future change that starts trusting
the block has to change the test on purpose.

Ghana and GHS are recorded regardless, so nothing downstream has to infer them.

Everything else
---------------
``employmentType`` is the bare string ``"FULL_TIME"`` here. ``datePosted``
carries no timezone ("2026-10-16T12:56:18"). ``hiringOrganization`` gives the
employer name, and ``title`` embeds it ("Accounts Clerk at L.T Company") -- the
structured field is preferred over parsing the title.

``SOURCE_HOME_COUNTRY`` supplies ``GH`` because ``addressCountry`` was not
present on the postings measured.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobwebghana.models import RawJobwebGhanaJob

#: ``ck_job_salaries_pay_period``: hourly, daily, weekly, monthly, yearly.
ALLOWED_PAY_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly", "yearly"})
_FALLBACK_PAY_PERIOD = "yearly"

_UNIT_MAP = {
    "HOUR": "hourly",
    "YEAR": "yearly",
    "MONTH": "monthly",
    "WEEK": "weekly",
    "DAY": "daily",
}

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "freelance",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "PERMANENT": "full_time",
    "PER_DIEM": None,
    "OTHER": None,
    "DEFAULT": None,
}

_COUNTRY_MAP = {"ghana": "GH", "gh": "GH"}


def _map_country(value: str | None) -> str | None:
    """``addressCountry`` -> ISO 3166-1 alpha-2."""
    if not value:
        return None
    key = value.strip().casefold()
    if key in _COUNTRY_MAP:
        return _COUNTRY_MAP[key]
    return value.strip() if re.fullmatch(r"[A-Z]{2}", value.strip()) else None


def _map_employment_type(value: str | list[str] | None) -> str | None:
    """schema.org ``employmentType`` -> a ``ref.employment_types.code``."""
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    for raw in items:
        key = re.sub(r"[^A-Z]+", "_", str(raw).strip().upper()).strip("_")
        if key in _EMPLOYMENT_MAP:
            mapped = _EMPLOYMENT_MAP[key]
            if mapped is not None:
                return mapped
    logger.warning(
        "Unrecognized Jobweb Ghana employmentType {!r} -- left None; the real "
        "value is preserved in raw_payload.",
        value,
    )
    return None


def _map_pay_period(unit_text: str | None) -> str:
    """Constrain ``unitText`` to the schema vocabulary.

    Explicit because the alternative is not a wrong number in one row: it is a
    check-constraint violation that aborts the transaction and fails every
    remaining row in the batch.
    """
    if not unit_text:
        return _FALLBACK_PAY_PERIOD
    mapped = _UNIT_MAP.get(unit_text.strip().upper())
    if mapped and mapped in ALLOWED_PAY_PERIODS:
        return mapped
    return _FALLBACK_PAY_PERIOD


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawJobwebGhanaJob, description: str) -> float:
    """Completeness, not plausibility.

    ``salary`` is scored on whether the board published a *usable* figure, so a
    placeholder does not read as a strength.
    """
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location or job.country),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "employment_type": bool(job.employment_type),
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobwebGhanaCleaner:
    """Turns ``RawJobwebGhanaJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobwebGhanaJob) -> CleanedJob:
        """Clean one posting."""
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        is_default = bool(raw_job.raw.get("salary_is_site_default"))
        # A placeholder is not a salary. See the module docstring.
        salary_min = None if is_default else raw_job.salary_min
        salary_max = None if is_default else raw_job.salary_max
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "country_raw": raw_job.country,
                "country_iso": _map_country(raw_job.country),
                "city": raw_job.city,
                "region": raw_job.region,
                "postal_code": raw_job.postal_code,
                "company_url": raw_job.company_url,
                "industry": raw_job.industry,
                "employment_type": raw_job.employment_type,
                "salary_unit_text": raw_job.salary_unit_text,
                # Kept so the rejection is auditable rather than silent.
                "salary_raw": raw_job.salary_raw,
                "salary_rejected": is_default,
                "salary_published": not is_default,
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            # Jobweb Ghana publishes no skills field.
            skills=[],
            location_cleaned=raw_job.location or _map_country(raw_job.country),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_min is not None or salary_max is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code=raw_job.salary_currency or "GHS",
            pay_period=_map_pay_period(raw_job.salary_unit_text),
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawJobwebGhanaJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Jobweb Ghana postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Jobweb Ghana posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

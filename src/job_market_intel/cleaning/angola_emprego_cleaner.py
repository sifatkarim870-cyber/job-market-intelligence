"""Cleans raw Angola Emprego postings into the shared ``CleanedJob`` contract.

Angola Emprego is **Angola** oriented and that is measured rather than assumed.

The employment-type trap
------------------------
``employmentType`` arrives as a **list** (``["FULL_TIME"]``). Every other
source in this project emits a bare string, so a cleaner written for them calls
``.strip()`` on it, raises ``AttributeError``, and -- because
``clean_jobs`` catches per record -- drops **every** posting in the batch while
reporting the run as a success. The mapper here accepts both shapes.

No salary
---------
``baseSalary`` is absent on every measured posting, so ``salary_disclosed`` is
always ``False`` and no ``pay_period`` is claimed about a figure that does not
exist. That makes this the fourth source in the corpus where that is true
(after Alfred, Net-Empregos and CareerJunction), and the coverage number should
be read as a fact about Angolan job postings rather than a scraper limitation.

Country
-------
``addressCountry`` was not consistently present on the postings measured, so
``SOURCE_HOME_COUNTRY`` supplies ``AO`` as the fallback -- which is what keeps
rows from collapsing onto the global-remote location.

Postings are in **Portuguese**. ``core.jobs.language_code`` plus the existing
translation kernel is the right place to handle that; nothing is translated at
scrape time.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.angola_emprego.models import RawAngolaEmpregoJob

#: ``ck_job_salaries_pay_period``: hourly, daily, weekly, monthly, yearly.
ALLOWED_PAY_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly", "yearly"})

#: schema.org ``employmentType`` -> ``ref.employment_types.code``.
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

#: ``addressCountry`` spellings -> ISO 3166-1 alpha-2.
_COUNTRY_MAP = {
    "angola": "AO",
    "ao": "AO",
}


def _map_country(value: str | None) -> str | None:
    """``addressCountry`` -> ISO 3166-1 alpha-2."""
    if not value:
        return None
    key = value.strip().casefold()
    if key in _COUNTRY_MAP:
        return _COUNTRY_MAP[key]
    if re.fullmatch(r"[A-Z]{2}", value.strip()):
        return value.strip()
    return None


def _map_employment_type(value: list[str] | str | None) -> str | None:
    """schema.org ``employmentType`` -> a ``ref.employment_types.code``.

    Accepts a **list** (what this board sends) or a bare string (what every
    other board sends). Multi-valued input is mapped by taking the first
    recognized entry, because ``ref.employment_types`` holds one code per job
    and inventing a precedence for FULL_TIME over PART_TIME would be a guess.
    """
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    for raw in items:
        key = re.sub(r"[^A-Z]+", "_", str(raw).strip().upper()).strip("_")
        if not key:
            continue
        if key in _EMPLOYMENT_MAP:
            mapped = _EMPLOYMENT_MAP[key]
            if mapped is not None:
                return mapped
            # A recognized-but-unmappable value (``PER_DIEM``, ``OTHER``,
            # ``DEFAULT``) must NOT end the search: a posting tagged
            # ``["PER_DIEM", "FULL_TIME"]`` is full-time as far as
            # ref.employment_types is concerned, and returning None here would
            # lose that. Keep looking.
    logger.warning(
        "Unrecognized Angola Emprego employmentType {!r} -- employment_type_code "
        "left None; the real value is still preserved in raw_payload.",
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


def _location_label(raw: RawAngolaEmpregoJob) -> str | None:
    """Prefer the joined label, fall back to the country.

    A country-only row is a real outcome here -- ``addressCountry`` is not
    consistently present -- so it is kept rather than dropped.
    """
    return raw.location or _map_country(raw.country) or None


def _quality_score(job: RawAngolaEmpregoJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
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


class AngolaEmpregoCleaner:
    """Turns ``RawAngolaEmpregoJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawAngolaEmpregoJob) -> CleanedJob:
        """Clean one posting."""
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        salary_min, salary_max = raw_job.salary_min, raw_job.salary_max
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "country_raw": raw_job.country,
                "country_iso": _map_country(raw_job.country),
                "city": raw_job.city,
                "region": raw_job.region,
                "industry": raw_job.industry,
                # Kept as the list it arrived as, so the shape is visible downstream.
                "employment_type": raw_job.employment_type,
                "listing_page": raw_job.listing_page,
                "salary_published": raw_job.salary_min is not None
                or raw_job.salary_max is not None,
                "language": "pt",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            # Angola Emprego publishes no skills field, so this is honestly empty
            # rather than empty because a parser missed something.
            skills=[],
            location_cleaned=_location_label(raw_job),
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
            # Angola is in the AOA zone; recorded so nothing downstream has to
            # infer it. No amount is ever stored against it.
            currency_iso_code=raw_job.salary_currency or "AOA",
            # No salary is published at all, so the period describes nothing.
            # The schema requires a value and every other cleaner defaults to
            # "yearly"; this stays a neutral placeholder rather than a claim.
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawAngolaEmpregoJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Angola Emprego postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Angola Emprego posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

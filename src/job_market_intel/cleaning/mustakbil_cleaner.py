"""Cleans raw Mustakbil postings into the shared ``CleanedJob`` contract.

Mustakbil is **Pakistan** oriented and that is measured rather than assumed:
``addressCountry`` is ``"PK"`` and the currency on every measured salary is PKR.
Both are read from the page.

Two things this board offers that most sources here do not:

* **A real experience requirement.** ``experienceRequirements`` is a nested
  ``{"@type": "OccupationalExperienceRequirements", "monthsOfExperience": 12}``
  node, so the corpus gets an actual figure rather than a free-text label.

* **Rich descriptions.** Measured 2-4k characters of structured duties and
  requirements lists, which is the same tier as Wellfound and Built In and far
  above the terse one-liners Apna often carries.

One deliberate deviation from the other cleaners: ``pay_period`` is ``monthly``,
not the ``yearly`` default. The only salary measured carried
``unitText: "MONTH"`` (PKR 40,000-60,000), and PKR 40,000 stored as an annual
figure would understate the role by an order of magnitude.

``CleanedJob.raw_payload`` is not persisted by ``JobRepository.save_cleaned_job``,
so ``direct_apply``, the raw experience text, the observed ``salary_shape`` and
the per-source hour-of-day figures ride in the payload and are discarded at save
time.
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
    from job_market_intel.scrapers.mustakbil.models import RawMustakbilJob

#: The only values ``salary.job_salaries.pay_period`` accepts. An out-of-range
#: value violates ``ck_job_salaries_pay_period``, which **aborts the enclosing
#: transaction** and fails every remaining row in the batch with it.
ALLOWED_PAY_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly", "yearly"})

#: Used only when nothing usable is known. Every measured Mustakbil salary was
#: MONTH, so a "yearly" default here would be actively wrong.
_FALLBACK_PAY_PERIOD = "monthly"

#: schema.org ``employmentType`` -> ``ref.employment_types.code``.
_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "freelance",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "APPRENTICESHIP": "apprenticeship",
    "PER_DIEM": None,
    "OTHER": None,
}


def _safe_pay_period(value: str | None) -> str:
    """Constrain a pay period to the schema's vocabulary.

    No literal braces in the message: loguru renders through ``str.format``, so
    "{hourly, ...}" would be read as a format field and raise KeyError from
    inside the logger.
    """
    if value in ALLOWED_PAY_PERIODS:
        return value
    if value:
        logger.warning(
            "Mustakbil pay period {!r} is outside the schema vocabulary "
            "(hourly, daily, weekly, monthly, yearly) -- falling back to {}. "
            "The raw value is still preserved in raw_payload.",
            value,
            _FALLBACK_PAY_PERIOD,
        )
    return _FALLBACK_PAY_PERIOD


def _map_employment_type(value: str | None) -> str | None:
    """schema.org ``employmentType`` -> a ``ref.employment_types.code``."""
    if not value:
        return None
    for segment in value.split(","):
        key = re.sub(r"[^A-Z]+", "_", segment.strip().upper()).strip("_")
        if not key:
            continue
        if key in _EMPLOYMENT_MAP:
            return _EMPLOYMENT_MAP[key]
    logger.warning(
        "Unrecognized Mustakbil employmentType {!r} -- employment_type_code "
        "left None; the real value is still preserved in raw_payload.",
        value,
    )
    return None


def _clean_description(body: str | None) -> str:
    """Unescape entities and strip the markup Mustakbil puts in ``description``.

    Unlike Apna, every measured posting here carries ``<b>``/``<ul>``/``<li>``
    inside the structured description, so this is doing real work rather than
    being defensive.
    """
    if not body:
        return ""
    return clean_html_text(html.unescape(body)) or ""


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _location_label(raw: RawMustakbilJob) -> str | None:
    """Prefer the joined label, fall back to country alone."""
    return raw.location or raw.country or None


def _quality_score(job: RawMustakbilJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location or job.country),
        "description": len(description) >= 200,
        "salary": job.salary_min is not None or job.salary_max is not None,
        "posted_date": job.posted_date is not None,
        "experience": job.months_of_experience is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class MustakbilCleaner:
    """Turns ``RawMustakbilJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawMustakbilJob) -> CleanedJob:
        """Clean one posting."""
        body = _clean_description(raw_job.description)

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_min is not None and salary_max is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "employment_type": raw_job.employment_type,
                "months_of_experience": raw_job.months_of_experience,
                "experience_requirements_raw": raw_job.experience_requirements_raw,
                "direct_apply": raw_job.direct_apply,
                "city": raw_job.city,
                "listing_path": raw_job.listing_path,
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            # Mustakbil publishes no skills field, so this is honestly empty
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
            # Read from the page, not assumed: every measured salary was PKR.
            currency_iso_code=raw_job.currency_iso_code or "PKR",
            pay_period=_safe_pay_period(raw_job.salary_period),
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawMustakbilJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Mustakbil postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Mustakbil posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

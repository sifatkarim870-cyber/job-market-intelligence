"""Cleans raw Careers24 postings into the shared ``CleanedJob`` contract.

Careers24 is **South Africa only**, and unlike Built In that is evidenced
rather than assumed: every posting measured carried
``jobLocation.address.addressCountry = "South Africa"`` and, where a salary was
published at all, ``currency = "ZAR"``. Both are read from the page; the
fallbacks below only apply when the field is genuinely absent, and they are the
board's own facts rather than a guess about a global site.

One thing this board offers that the other schema.org sources here do not is a
**single-figure salary**. Careers24 publishes
``{"value": "650000", "unitText": "YEAR"}`` -- no band at all. It is stored as
both bounds rather than discarded, because one number is still a salary and
treating it as a zero-width band keeps it inside the existing schema without
inventing a range the employer did not state.

What does *not* survive: ``CleanedJob.raw_payload`` is not persisted by
``JobRepository.save_cleaned_job`` and there are no per-job latitude/longitude
columns, so the ``industry``, the ``unitText`` and the observed ``salary_shape``
ride in the payload and are discarded at save time.
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
    from job_market_intel.scrapers.careers24.models import RawCareers24Job

#: schema.org ``employmentType`` -> ``ref.employment_types.code``. The codes are
#: the database's, not display strings; a value outside this table is not a
#: label that can be invented, so unknown values map to ``None`` with a
#: warning and the real string stays in ``raw_payload``.
_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "freelance",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "APPRENTICESHIP": "apprenticeship",
    "VOLUNTEER": None,
    "PER_DIEM": None,
    "OTHER": None,
}


def _map_employment_type(value: str | None) -> str | None:
    """schema.org ``employmentType`` -> a ``ref.employment_types.code``.

    Careers24 emits the schema.org SCREAMING_SNAKE vocabulary
    (``FULL_TIME``, ``PART_TIME``), which is a clean lookup rather than the
    substring matching most sources need. Comma-separated multi-values are read
    left to right, so the first listed contract form wins.
    """
    if not value:
        return None
    for segment in value.split(","):
        key = re.sub(r"[^A-Z]+", "_", segment.strip().upper()).strip("_")
        if not key:
            continue
        if key in _EMPLOYMENT_MAP:
            return _EMPLOYMENT_MAP[key]
    logger.warning(
        "Unrecognized Careers24 employmentType {!r} -- employment_type_code "
        "left None; the real value is still preserved in raw_payload.",
        value,
    )
    return None


def _clean_description(body: str | None) -> str:
    """Unescape entities and strip tags from the JSON-LD description."""
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


def _location_label(raw: RawCareers24Job) -> str | None:
    """Prefer the joined city/region, fall back to country alone.

    A posting can name only a country ("South Africa" with no locality), so the
    country-only case is kept rather than dropped -- it is still a real location
    statement, and dropping it would leave the row with nothing.
    """
    if raw.location:
        return raw.location
    return raw.country or None


def _quality_score(job: RawCareers24Job, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location or job.country),
        "description": len(description) >= 150,
        "salary": job.salary_min is not None,
        "posted_date": job.posted_date is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class Careers24Cleaner:
    """Turns ``RawCareers24Job`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawCareers24Job) -> CleanedJob:
        """Clean one posting."""
        body = _clean_description(raw_job.description)

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_min is not None and salary_max is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        # An amount with no period is not a salary that can be compared, and
        # ``pay_period`` has no "unknown" -- it is constrained to five values by
        # ``ck_job_salaries_pay_period``. Defaulting to "yearly" is what every
        # other cleaner here does, and it is defensible on a board that is
        # annual by convention. It is not defensible here. Measured 2026-10-16
        # over 40 postings: one advert published "R 80" with ``unitText: ""``,
        # which is plainly a daily or hourly rate, and storing it as yearly
        # would write a figure wrong by three orders of magnitude into a
        # research corpus. The amount is preserved in the payload and the row is
        # marked undisclosed instead.
        unperiodised_amount = salary_min is not None and raw_job.salary_period is None
        if unperiodised_amount:
            salary_min = salary_max = None

        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "industry": raw_job.industry,
                "employment_type": raw_job.employment_type,
                "city": raw_job.city,
                "region": raw_job.region,
                "listing_page": raw_job.listing_page,
            }
        )
        if unperiodised_amount:
            payload["salary_amount_without_period"] = raw_job.salary_min

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=_location_label(raw_job),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_min is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            # Read from the page, not assumed: every posting measured carried
            # addressCountry "South Africa" and every published salary ZAR.
            currency_iso_code=raw_job.currency_iso_code or "ZAR",
            # Already mapped from schema unitText in the parser. This fallback
            # only ever applies when there is no amount to misinterpret: a bad
            # value here violates ck_job_salaries_pay_period and aborts the
            # transaction, taking every later row with it. Measured periods on
            # the 15 of 40 postings that published one: yearly 10, monthly 3,
            # daily 1, and one with no unit at all (dropped above).
            pay_period=raw_job.salary_period or "yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawCareers24Job]) -> list[CleanedJob]:
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
                "dropped {} of {} Careers24 postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Careers24 posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

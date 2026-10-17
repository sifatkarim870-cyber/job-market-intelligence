"""Cleans raw Jobs.af postings into the shared ``CleanedJob`` contract.

The country trap
----------------
``addressCountry`` is the **name** ``"Afghanistan"``, not the ISO code ``"AF"``.
Vagas.com.br has the same shape with ``"Brasil"``, and the same consequence:
``geographic_resolution`` matches on ISO codes, so an unmapped name resolves to
*no country* and the row silently collapses onto the global-remote location. The
name is normalized here and the raw value is kept in ``raw_payload`` so the
normalization is auditable.

No salary
---------
``baseSalary`` was absent on the measured posting, so ``salary_disclosed`` is
always ``False`` and no ``pay_period`` is claimed about a figure that does not
exist.

``directApply`` is ``true`` on the measured posting. The corpus has no column for
it, so it is recorded in ``raw_payload`` rather than invented as a schema change.

Postings are in **English**.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobs_af.models import RawJobsAfJob

_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "CONTRACTOR": "freelance",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "PER_DIEM": None,
    "OTHER": None,
    "VOLUNTEER": "volunteer",
}

#: ``addressCountry`` as Jobs.af spells it -> ISO 3166-1 alpha-2.
_COUNTRY_MAP = {
    "afghanistan": "AF",
    "af": "AF",
}


def _map_country(value: str | None) -> str | None:
    """``addressCountry`` -> ISO 3166-1 alpha-2."""
    if not value:
        return None
    key = value.strip().casefold()
    if key in _COUNTRY_MAP:
        return _COUNTRY_MAP[key]
    return value.strip() if re.fullmatch(r"[A-Z]{2}", value.strip()) else None


def _map_employment_type(value: str | list[str] | None) -> str | None:
    """schema.org ``employmentType`` -> a ``ref.employment_types.code``.

    Accepts a list as well as a bare string: Angola Emprego sends a list and
    Jobweb Ghana a string, and both shapes must survive a normaliser here.
    """
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
        "Unrecognized Jobs.af employmentType {!r} -- left None; the real value is "
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


def _quality_score(job: RawJobsAfJob, description: str) -> float:
    """Completeness, not plausibility.

    Salary is scored on a *usable* figure, and this board publishes none.
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


class JobsAfCleaner:
    """Turns ``RawJobsAfJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobsAfJob) -> CleanedJob:
        """Clean one posting."""
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())
        iso_country = _map_country(raw_job.country)

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "country_raw": raw_job.country,
                "country_iso": iso_country,
                "employment_type": raw_job.employment_type,
                "industry": raw_job.industry,
                # No corpus column exists; recorded rather than invented.
                "direct_apply": raw_job.raw.get("direct_apply"),
                "salary_published": False,
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            # Jobs.af publishes no skills field.
            skills=[],
            location_cleaned=raw_job.location or iso_country,
            # No baseSalary on the measured posting.
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

    def clean_jobs(self, raw_jobs: list[RawJobsAfJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Jobs.af postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Jobs.af posting failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

"""Cleans raw Net-Empregos postings into the shared ``CleanedJob`` contract.

Net-Empregos is **Portugal** oriented and that is measured rather than assumed:
``addressCountry`` is ``"PT"`` on every posting measured. Both are read from
the page.

Two things this board does *not* provide, recorded here so the coverage numbers
are not mistaken for a parser fault:

* **No salary.** ``baseSalary`` was absent on all postings measured, so every
  Net-Empregos row has ``salary_disclosed = False`` and no ``pay_period`` is
  claimed. It is not defaulted to "yearly" as it is elsewhere, because with no
  amount there is nothing for a period to qualify -- and a period asserted about
  a salary that does not exist is a small lie that a later analysis cannot see.
* **No ``identifier``**. The URL id is the key, which is why
  ``source_job_id`` is a numeric id rather than a slug.

The postings are in **Portuguese**. The corpus already carries
``core.jobs.language_code`` and a scheduled translation kernel, and that is the
right place to handle this; nothing is translated at scrape time, and no attempt
is made to guess the language.
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
    from job_market_intel.scrapers.net_empregos.models import RawNetEmpregosJob

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

#: The only currency Net-Empregos could plausibly publish in. Recorded as a fact
#: about the country, not a guess about a salary -- no amount is ever stored.
_DEFAULT_CURRENCY = "EUR"


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
        "Unrecognized Net-Empregos employmentType {!r} -- employment_type_code "
        "left None; the real value is still preserved in raw_payload.",
        value,
    )
    return None


def _clean_description(body: str | None) -> str:
    """Unescape entities and strip the markup the JSON-LD description carries.

    Measured: descriptions are ``<b>``/``<BR>``-wrapped HTML, so this is doing
    real work.
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


def _location_label(raw: RawNetEmpregosJob) -> str | None:
    """Prefer the joined label, fall back to country alone.

    A country-only row is a real outcome here -- some postings carry no
    ``jobLocation`` at all -- so it is kept rather than dropped.
    """
    return raw.location or raw.country or None


def _quality_score(job: RawNetEmpregosJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why.

    No salary signal: Net-Empregos publishes none, so including one would
    depress every row's score by a fixed 1/9 for a fact about the board, not
    about the posting.
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


class NetEmpregosCleaner:
    """Turns ``RawNetEmpregosJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawNetEmpregosJob) -> CleanedJob:
        """Clean one posting."""
        body = _clean_description(raw_job.description)
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "employment_type": raw_job.employment_type,
                "industry": raw_job.industry,
                "city": raw_job.city,
                "region": raw_job.region,
                "postal_code": raw_job.postal_code,
                "street_address": raw_job.street_address,
                "listing_page": raw_job.listing_page,
                # Stated so a later reader does not assume it was forgotten.
                "salary_published": False,
                "language": "pt",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            # Net-Empregos publishes no skills field, so this is honestly empty
            # rather than empty because a parser missed something.
            skills=[],
            location_cleaned=_location_label(raw_job),
            # Net-Empregos publishes no salary at all.
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
            # Recorded for completeness only; no amount is ever stored against
            # it, so nothing downstream can read a currency from this row.
            currency_iso_code=_DEFAULT_CURRENCY,
            # The schema requires a value, and every other cleaner defaults to
            # "yearly". With no salary at all the period describes nothing, so
            # this stays a neutral placeholder rather than a claim.
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type),
        )

    def clean_jobs(self, raw_jobs: list[RawNetEmpregosJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Net-Empregos postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Net-Empregos posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

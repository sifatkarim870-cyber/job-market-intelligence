"""Cleans raw Vagas.com.br postings into the shared ``CleanedJob`` contract.

Vagas.com.br is **Brazil** oriented and that is measured rather than assumed.

The country trap
----------------
``addressCountry`` is the **name** ``"Brasil"``, not the ISO code ``"BR"``.
Every other country-carrying source in this project emits an ISO code (``PT``,
``ZA``). The name is normalized to ``BR`` here because
``geographic_resolution`` matches on ISO codes, and a row left as ``"Brasil"``
resolves to no country at all -- which is how rows end up silently collapsing
onto the global-remote location. ``"Brazil"`` is accepted too, because a board
can change its wording without notice and the cost of accepting it is one dict
entry.

The salary
----------
``baseSalary`` is present on roughly **one posting in three** (1 of 3 measured),
so salary coverage is partial *by nature of the board*, not by parser failure.
The layout nests ``unitText``/``minValue``/``maxValue`` **flat** under
``value`` -- a sixth distinct layout in this codebase, alongside Wellfound
(``value.minValue``), Careers24 (``value.value`` scalar), Apna and Mustakbil
(``value.value.minValue`` band) and Alfred (none).

``unitText`` is ``"MONTH"``, so the period is **monthly**, not the ``yearly``
default every other cleaner uses. Storing a monthly figure as annual would
overstate it twelvefold, and this is the second source after Apna where that
distinction is real.

The board publishes **no ``employmentType``** (0 of 3), so
``employment_type_code`` is always ``None`` -- honestly absent, not a parser gap.

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
    from job_market_intel.scrapers.vagas_com_br.models import RawVagasComBrJob

#: ``ref.currencies.iso_code`` for Brazil. Seeded already; verified present.
_CURRENCY = "BRL"

#: ``ck_job_salaries_pay_period``: hourly, daily, weekly, monthly, yearly.
ALLOWED_PAY_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly", "yearly"})
_FALLBACK_PAY_PERIOD = "yearly"

#: schema.org ``unitText`` -> the schema's pay-period vocabulary.
_UNIT_MAP = {
    "HOUR": "hourly",
    "YEAR": "yearly",
    "MONTH": "monthly",
    "WEEK": "weekly",
    "DAY": "daily",
}

#: ``addressCountry`` as Vagas.com.br spells it -> ISO 3166-1 alpha-2.
_COUNTRY_MAP = {
    "brasil": "BR",
    "brazil": "BR",
    "br": "BR",
}


def _map_country(value: str | None) -> str | None:
    """``addressCountry`` -> ISO 3166-1 alpha-2.

    The board sends the **name** ``"Brasil"``, which ``geographic_resolution``
    cannot match. Normalizing here is what stops every Vagas.com.br row from
    resolving to no country.
    """
    if not value:
        return None
    key = value.strip().casefold()
    mapped = _COUNTRY_MAP.get(key)
    if mapped:
        return mapped
    # An ISO code that is not in the map is already correct.
    if re.fullmatch(r"[A-Z]{2}", value.strip()):
        return value.strip()
    return None


def _map_pay_period(unit_text: str | None) -> str:
    """schema.org ``unitText`` -> the schema's pay-period vocabulary.

    Constrained explicitly because the alternative is not a wrong number in one
    row: it is a check-constraint violation that aborts the transaction and
    fails **every remaining row in the batch** with it.
    """
    if not unit_text:
        # No unitText means no claim can be made about the figure's period.
        # Every other cleaner defaults to "yearly"; here the salary only exists
        # at all when baseSalary did, so a missing unitText is a real gap worth
        # naming rather than a silent default.
        logger.warning(
            "vagas.com.br posting has a baseSalary but no unitText -- pay_period "
            "left at the yearly fallback, which may misstate a monthly figure. "
            "Re-measure the source before trusting the salary analysis."
        )
        return _FALLBACK_PAY_PERIOD
    mapped = _UNIT_MAP.get(unit_text.strip().upper())
    if mapped and mapped in ALLOWED_PAY_PERIODS:
        return mapped
    logger.warning(
        "Unrecognized vagas.com.br unitText {!r} -- pay_period falls back to {}. "
        "The raw value is still preserved in raw_payload.",
        unit_text,
        _FALLBACK_PAY_PERIOD,
    )
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


def _location_label(raw: RawVagasComBrJob) -> str | None:
    """Prefer the joined label, fall back to the country.

    A country-only row is a real outcome here -- some postings carry no
    ``jobLocation`` at all -- so it is kept rather than dropped.
    """
    return raw.location or _map_country(raw.country) or None


def _quality_score(job: RawVagasComBrJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.location or job.country),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "closing_date": job.closing_date is not None,
        "url": bool(job.url),
        "salary": job.salary_min is not None or job.salary_max is not None,
    }
    return round(sum(signals.values()) / len(signals), 2)


class VagasComBrCleaner:
    """Turns ``RawVagasComBrJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawVagasComBrJob) -> CleanedJob:
        """Clean one posting."""
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())
        iso_country = _map_country(raw_job.country)

        salary_min, salary_max = raw_job.salary_min, raw_job.salary_max
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            # Swapped rather than dropped: the source had them reversed.
            salary_min, salary_max = salary_max, salary_min

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "country_raw": raw_job.country,
                "country_iso": iso_country,
                "city": raw_job.city,
                "region": raw_job.region,
                "job_benefits": raw_job.job_benefits,
                "industry": raw_job.industry,
                "employment_type": raw_job.employment_type,
                "salary_unit_text": raw_job.salary_unit_text,
                "listing_page": raw_job.listing_page,
                "language": "pt",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            # Vagas.com.br publishes no skills field, so this is honestly empty
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
            currency_iso_code=raw_job.salary_currency or _CURRENCY,
            # Monthly, not the "yearly" default: unitText is "MONTH" on every
            # measured figure, and storing a monthly number as annual would
            # overstate it twelvefold.
            pay_period=_map_pay_period(raw_job.salary_unit_text),
            # The board publishes no employmentType (0 of 3), so this is
            # honestly None rather than a guessed default.
            employment_type_code=None,
        )

    def clean_jobs(self, raw_jobs: list[RawVagasComBrJob]) -> list[CleanedJob]:
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
                "dropped {} of {} vagas.com.br postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every vagas.com.br posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

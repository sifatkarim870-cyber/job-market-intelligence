"""Cleans raw Revolico (Cuba) ads into ``CleanedJob``.

Ads are written in **Spanish**. The board publishes no employer field and no
salary field, so both are left empty rather than inferred: every row cites
"Unknown employer" and discloses no pay, and the raw ``price``/``currency``
(often a placeholder ``1``, and absent on 55 of 102 sampled ads) is kept in
``raw_payload`` only.

``currency_iso_code`` is the home-market ``CUP`` even though no row discloses
pay, matching the convention every classifieds cleaner here follows (see
``lexpress_mu_cleaner``); it is what the row's currency *would* be, not a claim
that it was advertised.

A remote-work phrase (``teletrabajo`` / ``trabajo remoto`` / ...) is recorded
in ``raw_payload`` but does **not** set ``remote_work_type_code``: a
classifieds line saying "remote" never states how remote, so mapping it to
``remote_country``/``remote_global`` would be a guess.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text

if TYPE_CHECKING:
    from job_market_intel.scrapers.revolico_cu.models import RawRevolicoCuJob


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawRevolicoCuJob, description: str) -> float:
    """A 0.0-1.0 completeness score over the fields Revolico can supply.

    Deliberately excludes employer and salary: no Revolico ad carries either,
    so scoring them would cap every row below 1.0 for a property of the board
    rather than a property of the ad.
    """
    signals = {
        "title": bool(job.title and job.title.strip()),
        "location": bool(job.location),
        "description": len(description) >= 200,
        "posted_date": job.posted_date is not None,
        "url": bool(job.url),
        "category": bool(job.category),
        "phone": bool(job.phone),
    }
    return round(sum(signals.values()) / len(signals), 2)


class RevolicoCuCleaner:
    """Turns ``RawRevolicoCuJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawRevolicoCuJob) -> CleanedJob:
        body = clean_html_text(raw_job.description or "") or ""
        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "category": raw_job.category,
                "subcategory_slug": raw_job.subcategory_slug,
                "poster_name": raw_job.poster_name,
                "price_raw": raw_job.price,
                "price_currency": raw_job.price_currency,
                "price_is_reliable": False,
                "salary_published": False,
                "updated_on": raw_job.updated_on,
                "phone": raw_job.phone,
                "remote_phrase": raw_job.remote_phrase,
                "listing_page": raw_job.listing_page,
                "language": "es",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=None,
            skills=[],
            location_cleaned=raw_job.location or "Cuba",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=None,
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            currency_iso_code="CUP",
            pay_period="yearly",
            employment_type_code=None,
        )

    def clean_jobs(self, raw_jobs: list[RawRevolicoCuJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Revolico ads that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Revolico ad failed cleaning -- the scraper will report "
                "success while persisting nothing"
            )
        return cleaned

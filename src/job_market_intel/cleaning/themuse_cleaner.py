"""Cleans validated The Muse records into standardized, storage-ready records.

The Muse is employer-authored, so the description is first-party text rather
than an aggregator's summary -- which is why this source is worth the
pagination cost even though it reports no salary at all.

Two mappings worth stating:

``original_url``
    The API carries no canonical job URL, only ``refs.landing_page`` pointing at
    the company page the posting came from. When that is missing the cleaner
    builds a stable synthetic URL from the id, because
    ``core.jobs.original_url`` is NOT NULL and an empty string would pass the
    column but make every row indistinguishable.

``pay_period``
    No salary fields are published, so ``salary_disclosed`` is False and the
    period is the schema's neutral default. ``CleanedJob.pay_period`` is a
    required ``str`` -- passing None raises ``string_type`` and drops the row,
    which is how this was found.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.themuse.models import RawThemuseJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 50

#: See jobicy_cleaner for why this is required and why "yearly" is the honest
#: neutral value for a source that reports no salary.
DEFAULT_PAY_PERIOD = "yearly"


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Four-signal completeness score, identical in shape and weighting to
    every other cleaner's, so the number stays comparable across sources."""
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


class ThemuseCleaner:
    """Turns ``RawThemuseJob`` objects into ``CleanedJob`` records."""

    def clean_jobs(self, jobs: list[RawThemuseJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        for raw in jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to clean The Muse job {}: {}", raw.id, exc)
        return cleaned

    def clean_job(self, raw: RawThemuseJob) -> CleanedJob:
        description_clean = clean_html_text(raw.contents)
        word_count = len(description_clean.split()) if description_clean else 0

        # Category and level are this feed's tag list; tags are a separate
        # object list on some records, so both contribute.
        skills: list[str] = []
        seen: set[str] = set()
        for value in (raw.category_text, raw.level_text):
            for part in (value or "").split(","):
                label = clean_plain_text(part)
                if label and label.lower() not in seen:
                    seen.add(label.lower())
                    skills.append(label)

        location_cleaned = raw.location_text

        return CleanedJob(
            source_job_id=raw.id,
            job_title=clean_plain_text(raw.name) or raw.name,
            company_name=clean_plain_text(raw.company_name) or raw.company_name or "Unknown",
            # The public API does not expose company logos.
            company_logo_url=None,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw.apply_url,
            # original_url is NOT NULL; a synthetic but stable URL beats an
            # empty string that makes every row indistinguishable.
            original_url=raw.apply_url or f"https://www.themuse.com/jobs/{raw.id}",
            posting_date=raw.posting_date,
            closing_date=None,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=False,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw.raw_payload,
            currency_iso_code="USD",
            pay_period=DEFAULT_PAY_PERIOD,
            # The API publishes no employment type.
            employment_type_code=None,
        )

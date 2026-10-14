"""Cleans raw Wellfound postings into the shared ``CleanedJob`` contract.

Wellfound is a startup board, which changes three things:

* **Titles are already normalised.** No ALL-CAPS shouting, so no title-casing
  is needed -- unlike USAJOBS, where doing it wrong would have been worse than
  not doing it at all.
* **Salary is unusually complete.** 6 of 6 postings sampled carried an explicit
  ``minValue``/``maxValue`` in a named currency with a ``unitText``. That makes
  ``salary_disclosed`` genuinely meaningful here rather than a guess, so it is
  driven by the presence of a figure, not by the posting looking professional.
* **A posting can name several offices.** The sample roles named both Denver
  and San Francisco; one named seven countries. They are joined rather than
  truncated, because a multi-location posting is a real and common fact on this
  board and dropping the rest would understate where the work can be done.

What does *not* survive: ``CleanedJob.raw_payload`` is not persisted by
``JobRepository.save_cleaned_job`` and there are no columns for the office
coordinates, so those ride in the payload and are discarded at save time.
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
    from job_market_intel.scrapers.wellfound.models import RawWellfoundJob

#: Page furniture Wellfound repeats on every posting.
_BOILERPLATE = (
    "apply now",
    "save job",
    "share this job",
    "report this job",
    "sign up",
    "already have an account",
)

#: A very long join of offices stops being a location and starts being noise.
_MAX_LOCATIONS_JOINED = 6


def _strip_boilerplate(body: str | None) -> str:
    """Drop repeated navigation lines, unescape entities, keep the posting."""
    if not body:
        return ""
    kept = [
        line.strip()
        for line in body.split("\n")
        if line.strip() and line.strip().lower() not in _BOILERPLATE
    ]
    return clean_html_text(html.unescape("\n".join(kept))) or ""


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _location_label(raw: RawWellfoundJob) -> str | None:
    """Join the offices the posting names, most useful first."""
    parts = [loc for loc in raw.locations if loc][:_MAX_LOCATIONS_JOINED]
    if not parts:
        # Fall back to the country list: a remote-everywhere posting names no
        # city but does name countries, and "United Kingdom" is a better
        # location than nothing.
        parts = list(raw.location_countries)[:_MAX_LOCATIONS_JOINED]
    return ", ".join(parts) if parts else None


def _quality_score(job: RawWellfoundJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.company_name and job.company_name.strip()),
        "location": bool(job.locations or job.location_countries),
        "description": len(description) >= 200,
        "salary": job.salary_min is not None,
        "posted_date": job.posted_date is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class WellfoundCleaner:
    """Turns ``RawWellfoundJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawWellfoundJob) -> CleanedJob:
        """Clean one posting."""
        body = _strip_boilerplate(raw_job.description)
        # Benefits are real content on a startup posting (equity, parental
        # leave) but they are not the job description, so they are appended
        # under a heading rather than merged into the duties text.
        if raw_job.benefits:
            benefits = clean_html_text(html.unescape(raw_job.benefits)) or ""
            if benefits and benefits.lower() not in body.lower():
                body = f"{body}\n\nBenefits\n{benefits}" if body else f"Benefits\n{benefits}"

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_max is not None and salary_min is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())
        # Multi-location postings would otherwise report a single location and
        # understate where the job can be done. is_global_remote stays unset:
        # this board is location-flexible, not remote-first, and claiming a
        # worldwide opening would be the same factual overclaim this project
        # has already had to undo once.

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "industry": raw_job.industry,
                "employment_type": raw_job.employment_type,
                "direct_apply": raw_job.direct_apply,
                "company_website": raw_job.company_website,
                "locations": raw_job.locations,
                "location_countries": raw_job.location_countries,
                "organization_locations": raw_job.organization_locations,
                "listing_path": raw_job.listing_path,
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            company_name=company or "Unknown employer",
            company_logo_url=raw_job.company_logo_url,
            skills=[],
            location_cleaned=_location_label(raw_job),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_min is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            # directApply was true on every posting sampled, so there is no
            # separate application URL; the posting URL is the apply surface.
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            # Taken from the JSON-LD baseSalary currency, not defaulted to USD:
            # a London or Berlin posting states GBP or EUR, and assuming USD
            # would write a wrong currency into every non-US row.
            currency_iso_code=raw_job.currency_iso_code or "USD",
            # Already mapped from schema unitText into the corpus vocabulary in
            # the parser. The fallback matters: a bad value violates
            # ck_job_salaries_pay_period and aborts the transaction, taking
            # every later row with it.
            pay_period=raw_job.salary_period or "yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawWellfoundJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Wellfound postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Wellfound posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

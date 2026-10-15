"""Cleans raw Built In postings into the shared ``CleanedJob`` contract.

Built In differs from the other schema.org sources in one way that matters here:
it is **US-only**. Every posting measured carried
``applicantLocationRequirements: {"@type": "Country", "name": "USA"}``, so the
currency is genuinely always USD and the country genuinely always the US.
Neither is guessed -- both are read from the page -- but it is worth stating
because it is the one place where the same-looking default would have been
right by accident rather than by evidence.

Two things this board offers that no other source here does:

* **46 benefits on a single posting.** ``jobBenefits`` is a list of short
  strings ("Offers 401(K)", "Provides adoption assistance"), and they are
  appended under their own heading rather than merged into the duties text --
  they are real content but they are not the job description.
* **An explicit remote flag.** ``jobLocationType`` is ``"TELECOMMUTE"`` on
  remote roles. That maps onto ``core.jobs.remote_work_type_id`` via the
  repository, so remote postings are distinguishable from on-site ones here
  rather than being inferred from the location text.

What does *not* survive: ``CleanedJob.raw_payload`` is not persisted by
``JobRepository.save_cleaned_job`` and there are no per-job latitude/longitude
columns, so the coordinates, the applicant-country list, the industry list and
the benefit list ride in the payload and are discarded at save time.
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
    from job_market_intel.scrapers.builtin.models import RawBuiltInJob

#: Page furniture Built In repeats on every posting.
_BOILERPLATE = (
    "apply now",
    "save job",
    "share",
    "report this job",
    "sign up",
)

#: A very long join of locations stops being a location and starts being noise.
_MAX_LOCATIONS_JOINED = 8


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


def _location_label(raw: RawBuiltInJob) -> str | None:
    """Join the locations the posting names, most specific first.

    A posting can name several states with no city ("Pennsylvania"), so the
    state-only case is kept rather than dropped -- it is still a real location
    statement, and dropping it would leave the row with nothing.
    """
    parts = [loc for loc in raw.locations if loc][:_MAX_LOCATIONS_JOINED]
    if not parts:
        parts = list(raw.location_countries)[:_MAX_LOCATIONS_JOINED]
    return ", ".join(parts) if parts else None


def _quality_score(job: RawBuiltInJob, description: str) -> float:
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


class BuiltInCleaner:
    """Turns ``RawBuiltInJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawBuiltInJob) -> CleanedJob:
        """Clean one posting."""
        body = _strip_boilerplate(raw_job.description)
        if raw_job.benefits:
            # One line per benefit, under its own heading. Joined into a single
            # comma-run it becomes unreadable, and 46 of them is a wall.
            joined = "\n".join(f"- {b}" for b in raw_job.benefits)
            body = f"{body}\n\nBenefits\n{joined}" if body else f"Benefits\n{joined}"

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_max is not None and salary_min is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        company = re.sub(r"\s+", " ", (raw_job.company_name or "").strip())

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                "industries": raw_job.industries,
                "employment_type": raw_job.employment_type,
                "direct_apply": raw_job.direct_apply,
                "is_remote": raw_job.is_remote,
                "company_page_url": raw_job.company_page_url,
                "benefits": raw_job.benefits,
                "locations": raw_job.locations,
                "location_countries": raw_job.location_countries,
                "applicant_countries": raw_job.applicant_countries,
                "coordinates": raw_job.coordinates,
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
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.closing_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=payload,
            # Read from the page, not assumed: this board is US-only and every
            # posting measured carried a USD baseSalary.
            currency_iso_code=raw_job.currency_iso_code or "USD",
            # Already mapped from schema unitText in the parser. The fallback
            # matters: a bad value violates ck_job_salaries_pay_period and
            # aborts the transaction, taking every later row with it.
            pay_period=raw_job.salary_period or "yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawBuiltInJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Built In postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Built In posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

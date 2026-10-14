"""Cleans raw Job Bank Canada postings into the shared ``CleanedJob`` contract.

Job Bank is bilingual by statute, so two things matter here that do not for the
English-only sources: the page can arrive in French, and employer names carry
both languages joined by a pipe ("Export Development Canada | Exportation et
developpement Canada"). Storing the joined form would create a distinct
company entity from every other way that employer is written, which is exactly
what ``core.companies`` exists to prevent -- so the French half is dropped
here rather than left for the entity resolver to trip over.
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
    from job_market_intel.scrapers.jobbank.models import RawJobBankJob

#: "Export Development Canada | Exportation et developpement Canada"
_BILINGUAL = re.compile(r"\s*\|\s*[^\|]{3,}$")

#: Job Bank's page furniture, repeated on every posting fed by an aggregator.
_BOILERPLATE = (
    "save to favourites",
    "your favourites",
    "sign in or sign up",
    "export",
    "copy link",
    "email",
    "job detail",
    "median wage",
    "quick stats",
    "date modified",
)


def _first_line(text: str | None) -> str | None:
    """Job Bank's description opens with the title and a 'Title posted on' line."""
    if not text:
        return None
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.lower() in _BOILERPLATE or s.lower().startswith("title posted on"):
            continue
        return s
    return None


def _strip_boilerplate(body: str | None) -> str:
    """Drop the repeated navigation-ish lines, keep the posting."""
    if not body:
        return ""
    kept = [
        line.strip()
        for line in body.split("\n")
        if line.strip() and line.strip().lower() not in _BOILERPLATE
    ]
    return clean_html_text(html.unescape("\n".join(kept))) or ""


def _employer_name(raw_employer: str | None) -> str:
    """Keep the English half of a bilingual employer name."""
    if not raw_employer:
        return "Unknown employer"
    name = _BILINGUAL.sub("", raw_employer).strip()
    return name or raw_employer.strip() or "Unknown employer"


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _quality_score(job: RawJobBankJob, description: str) -> float:
    """Completeness, not plausibility -- see every other cleaner for why."""
    signals = {
        "title": bool(job.title and job.title.strip()),
        "employer": bool(job.employer and job.employer.strip()),
        "location": bool(job.location and job.location.strip()),
        "description": len(description) >= 200,
        "salary": job.salary_min is not None,
        "posted_date": job.posted_date is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobBankCleaner:
    """Turns ``RawJobBankJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobBankJob) -> CleanedJob:
        """Clean one posting.

        The description's first line is dropped: it repeats the posting title
        verbatim ("software developer" for a posting titled "Sr Software
        Developer"), and carrying it into ``description_clean`` inflates the
        word count and gives the classifier a free copy of a field it already
        has.
        """
        body = _strip_boilerplate(raw_job.description)
        title = raw_job.title.strip()
        lines = body.split("\n")
        if lines and lines[0].strip() == title:
            body = "\n".join(lines[1:]).strip()

        salary_min = int(raw_job.salary_min) if raw_job.salary_min is not None else None
        salary_max = int(raw_job.salary_max) if raw_job.salary_max is not None else None
        if salary_max is not None and salary_min is not None and salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=title,
            company_name=_employer_name(raw_job.employer),
            company_logo_url=None,
            skills=[],
            location_cleaned=(raw_job.location or "").strip() or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_min is not None,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            posting_date=_to_datetime(raw_job.posted_date),
            closing_date=_to_datetime(raw_job.deadline_date),
            data_quality_score=_quality_score(raw_job, body),
            raw_payload=raw_job.raw or {},
            # Canadian postings are in CAD unless the text says otherwise.
            currency_iso_code="CAD",
            # "yearly", not "annually": salary.job_salaries.
            # ck_job_salaries_pay_period admits only
            # hourly/daily/weekly/monthly/yearly, and this default is what
            # runs when the posting states a figure with no period word
            # ("$68,000 to $78,000"). Getting it wrong failed 25 of 30 rows on
            # the first real run -- the violation aborts the transaction, so
            # every row after the first bad one dies too.
            pay_period=raw_job.pay_period or "yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawJobBankJob]) -> list[CleanedJob]:
        """Clean a batch, dropping postings that cannot produce a usable record.

        Failures are logged, not swallowed. An earlier version caught
        ``Exception`` and continued with no output at all, which turned a
        one-word typo in a field name into "Cleaned: 0" on every run with no
        clue why -- the same silent-empty-result failure this project has hit
        in three other places.
        """
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001 - one bad posting must not stop the batch
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Job Bank postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        return cleaned

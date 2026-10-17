"""Cleans raw Job in Rwanda postings into the shared ``CleanedJob`` contract.

Two facts about this board shape the whole cleaner, and both are measured:

**There is no posting date.** Of six detail pages inspected, four carry no date
at all and the two that do carry a *deadline* in prose. So ``posting_date`` is
``None`` on every Job in Rwanda row, and ``closing_date`` is populated only
where the page says "deadline". That is recorded in ``raw_payload`` as
``deadline_phrase`` so the extraction can be audited, and it means any freshness
analysis over this source has to exclude it rather than treat the NULL as
"unknown".

**There is no company field.** The employer is only inferable from the posting
prose ("The Management of RATWA SACCO HUYE informs..."), which is a sentence,
not a field. ``company_name`` stays "Unknown employer" -- guessing a legal
entity out of prose would put unverifiable strings into ``core.companies``.

No salary is published either, so ``salary_disclosed`` is always ``False`` and
no ``pay_period`` is claimed about a figure that does not exist. Rwanda is
supplied by ``SOURCE_HOME_COUNTRY`` because the board publishes no country
field either.

The site is in English, so no language handling is needed.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob

if TYPE_CHECKING:
    from job_market_intel.scrapers.jobinrwanda.models import RawJobInRwandaJob


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day)
    except AttributeError:
        return None


def _storable_closing_date(job: RawJobInRwandaJob) -> tuple[datetime | None, bool]:
    """The deadline, but only when it is still open.

    Returns ``(closing_date, dropped_because_expired)``.

    Why this guard exists
    --------------------
    ``job_repository.save_cleaned_job`` defaults a NULL ``posting_date`` to
    ``date.today()``::

        p_date = job.posting_date.date() if isinstance(...) else (job.posting_date or date.today())

    This board publishes no posting date at all, so every one of its rows would
    claim to have been posted *today*. A deadline that has already passed --
    5 October 2026 on a run dated 17 October -- then sits **before** that
    fabricated posting date and trips::

        ck_jobs_closing_after_posting

    which failed the row outright: 1 of 40 postings was lost to it on the first
    live run.

    Two problems are tangled together here. One -- the repository's ``today``
    fallback inventing a publication date for an undated source -- is
    pre-existing and shared, so it is reported rather than changed here. The
    other is local and fixable: an **expired** deadline is not a closing date.
    The phrase is kept in ``raw_payload`` so nothing is lost.
    """
    if job.closing_date is None:
        return None, False
    if job.closing_date < date.today():
        return None, True
    return _to_datetime(job.closing_date), False


def _quality_score(job: RawJobInRwandaJob, description: str, closing: datetime | None) -> float:
    """Completeness, not plausibility -- see every other cleaner for why.

    Three of the eight signals below are structurally always false on this board
    (employer, posted date, salary), which is exactly why they are not weighted:
    including them would give every Job in Rwanda row the same depressed score
    and make the number useless for ranking *this* source's quality.
    """
    signals = {
        "title": bool(job.title and job.title.strip()),
        "description": len(description) >= 200,
        "closing_date": closing is not None,
        "url": bool(job.url),
    }
    return round(sum(signals.values()) / len(signals), 2)


class JobInRwandaCleaner:
    """Turns ``RawJobInRwandaJob`` records into ``CleanedJob``."""

    def clean_job(self, raw_job: RawJobInRwandaJob) -> CleanedJob:
        """Clean one posting."""
        body = re.sub(r"\s+", " ", (raw_job.description or "").strip())
        closing, expired = _storable_closing_date(raw_job)

        payload = dict(raw_job.raw or {})
        payload.update(
            {
                # Why posting_date is None, spelled out for a later reader.
                "has_posting_date": False,
                "has_company_field": False,
                "salary_published": False,
                "deadline_phrase": raw_job.raw.get("deadline_phrase"),
                # The deadline the page stated, even when it had already passed
                # and so could not be stored as a closing date.
                "deadline_expired": expired,
                "title_tag": raw_job.raw.get("title_tag"),
                "listing_page": raw_job.listing_page,
                "language": "en",
            }
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.title.strip(),
            # No company field exists; see the module docstring.
            company_name=raw_job.company_name or "Unknown employer",
            company_logo_url=None,
            # No skills field on this board.
            skills=[],
            # The board publishes no location field, but
            # ``resolve_and_cache_location`` returns ``None`` immediately when
            # ``raw_location_text`` is ``None`` -- it never reaches the
            # ``SOURCE_HOME_COUNTRY`` fallback. Leaving this NULL therefore
            # gave every row ``location_id = NULL``: no country *and* no
            # global-remote flag, which is the worst of both. Naming the board's
            # own country is the honest statement and is what lets the
            # resolver do its job.
            location_cleaned="Rwanda",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=len(body.split()),
            apply_url=raw_job.url,
            original_url=raw_job.url or "",
            # The board publishes no posting date -- but `core.jobs` is RANGE
            # partitioned on posting_date and the column is NOT NULL, so
            # `job_repository` substitutes `date.today()` (line ~404). That is
            # load-bearing by design, not a defect: a NULL would leave the row
            # unroutable to any partition. The consequence is that every Job in
            # Rwanda row is stamped with the run date, so **any recency or
            # freshness analysis must exclude this source** rather than read the
            # date as a publication date. See the module docstring.
            posting_date=None,
            closing_date=closing,
            data_quality_score=_quality_score(raw_job, body, closing),
            raw_payload=payload,
            # No salary published, so no amount can ever be stored against this.
            currency_iso_code="RWF",
            # The schema requires a value and every other cleaner defaults to
            # "yearly"; with no salary the period describes nothing.
            pay_period="yearly",
            # No employment type published.
            employment_type_code=None,
        )

    def clean_jobs(self, raw_jobs: list[RawJobInRwandaJob]) -> list[CleanedJob]:
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
                "dropped {} of {} Job in Rwanda postings that could not be cleaned: {}",
                len(failures),
                len(raw_jobs),
                failures[:3],
            )
        if raw_jobs and not cleaned:
            logger.error(
                "every Job in Rwanda posting failed cleaning -- the scraper will "
                "report success while persisting nothing"
            )
        return cleaned

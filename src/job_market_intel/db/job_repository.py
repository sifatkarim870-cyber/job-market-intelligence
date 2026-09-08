"""db.job_repository
=================

Repository implementation for storing, updating, and deduplicating job records
and managing scraping sessions in PostgreSQL.

Supports Step 9 (PostgreSQL Persistence), Step 10 (Same-Source Duplicate &
Update Detection via SHA-256 content hashing), and Step 27 (Salary
Standardization).

Step 27 note: unlike company resolution (Step 25) and skill extraction
(Step 26), salary normalization runs inline here rather than as a
separate batch job in ``normalization/`` -- see
``normalization/salary_standardization.py``'s module docstring for why
(every input it needs is already available at ingestion time). This
module calls ``normalize_annual_salary`` the same way it already calls
``get_or_create_company``.

Step 28 note: geographic resolution ALSO runs inline here, for a
stronger reason than salary's -- it's not optional convenience, it's the
only place it CAN run. ``job.location_cleaned`` is never persisted
anywhere in the schema (it feeds ``compute_job_content_hash`` below and
nothing else), so a deferred batch job would have no raw text left to
resolve once a job is already in ``core.jobs``. See
``normalization/geographic_resolution.py``'s module docstring for the
full rationale. This module calls ``resolve_and_cache_location`` the
same way it already calls ``get_or_create_company`` and
``normalize_annual_salary``.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.db.exceptions import RepositoryError
from job_market_intel.db.repository import AbstractRepository
from job_market_intel.db.transaction import transaction
from job_market_intel.normalization.geographic_resolution import resolve_and_cache_location
from job_market_intel.normalization.salary_standardization import normalize_annual_salary

if TYPE_CHECKING:
    from job_market_intel.cleaning.common import CleanedJob

#: Pay period assumed for every job persisted by this repository. None of
#: the three live sources (RemoteOK, We Work Remotely, Remotive) captures
#: pay period explicitly -- confirmed: no ``pay_period`` field exists on
#: ``CleanedJob`` or any raw source model. This assumption is reasonable
#: for these three sources specifically (RemoteOK's own docs describe its
#: salary fields as annual; Remotive's free-text parser only matches
#: whole-dollar range strings typical of annual tech-salary postings; WWR
#: has no salary field at all) but it IS an assumption, not something this
#: code verifies per-record -- named as a constant, rather than a bare
#: string literal, specifically so it stays a visible, revisitable
#: decision rather than a buried one. Revisit if/when a source that
#: reports salary at a different cadence (e.g. an hourly-rate contractor
#: board) is added.
_ASSUMED_PAY_PERIOD = "yearly"

#: ISO 4217 code assumed for every job persisted by this repository, for
#: the same reason ``_ASSUMED_PAY_PERIOD`` is: all three live sources are
#: USD-only by construction of their own raw models (see
#: ``normalization/salary_standardization.py``'s module docstring), not by
#: an assumption layered on afterward.
_ASSUMED_CURRENCY_ISO_CODE = "USD"


def compute_job_content_hash(
    job_title: str,
    company_name: str,
    description_clean: str | None,
    location_cleaned: str | None,
    salary_min: int | float | None,
    salary_max: int | float | None,
) -> str:
    """Computes a deterministic SHA-256 hash of immutable/substantive job fields.

    Used for change detection on re-scrape: if content_hash is identical to an
    existing record, the job is marked UNCHANGED. If it differs, the record is
    marked UPDATED and field updates are applied.
    """
    payload = (
        f"{job_title.strip()}|"
        f"{company_name.strip().lower()}|"
        f"{(description_clean or '').strip()}|"
        f"{(location_cleaned or '').strip().lower()}|"
        f"{salary_min or ''}|"
        f"{salary_max or ''}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class JobRepository(AbstractRepository[Any]):
    """Repository for managing core.jobs, core.companies, core.job_descriptions,
    salary.job_salaries, and ops.scraping_sessions.
    """

    # This repository issues raw SQL against several tables (core.jobs,
    # core.companies, core.job_descriptions, salary.job_salaries,
    # ops.scraping_sessions) rather than mapping to a single ORM model, so it
    # has no meaningful value for AbstractRepository's `model: type[T]`
    # contract. `__init__` below overrides the base class's `hasattr(model)`
    # check accordingly. The assignment below is a deliberate, understood
    # deviation from that contract, not an oversight.
    model = None  # type: ignore[assignment]

    def __init__(self) -> None:
        # Override parent check requiring self.model
        pass

    def get_by_id(self, session: Session, entity_id: Any) -> Any | None:
        row = session.execute(
            text(
                "SELECT job_id, source_id, source_job_id, job_title, posting_date, content_hash "
                "FROM core.jobs WHERE job_id = :job_id"
            ),
            {"job_id": entity_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_all(
        self, session: Session, *, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        rows = session.execute(
            text(
                "SELECT job_id, source_id, source_job_id, job_title, posting_date, content_hash "
                "FROM core.jobs ORDER BY job_id DESC LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        ).all()
        return [dict(r._mapping) for r in rows]

    def add(self, session: Session, entity: Any) -> Any:
        raise NotImplementedError("Use save_cleaned_job or save_cleaned_jobs instead.")

    def update(self, session: Session, entity: Any) -> Any:
        raise NotImplementedError("Use save_cleaned_job or save_cleaned_jobs instead.")

    def delete(self, session: Session, entity: Any) -> None:
        if isinstance(entity, (int, str)):
            session.execute(
                text("UPDATE core.jobs SET job_status = 'removed' WHERE job_id = :job_id"),
                {"job_id": entity},
            )

    def count(self, session: Session) -> int:
        return session.execute(text("SELECT count(*) FROM core.jobs")).scalar() or 0

    # --- Scraping Session Helpers ---

    def create_scraping_session(
        self,
        session: Session,
        source_id: int,
        scraper_version: str = "0.1.0",
        trigger_type: str = "manual",
    ) -> int:
        """Create a new ops.scraping_sessions entry and return its session_id."""
        result = session.execute(
            text(
                "INSERT INTO ops.scraping_sessions "
                "(source_id, started_at, status, scraper_version, trigger_type) "
                "VALUES (:source_id, now(), 'running', :scraper_version, :trigger_type) "
                "RETURNING session_id"
            ),
            {
                "source_id": source_id,
                "scraper_version": scraper_version,
                "trigger_type": trigger_type,
            },
        ).scalar()
        if result is None:
            raise RepositoryError("Failed to create ops.scraping_sessions record.")
        return int(result)

    def finish_scraping_session(
        self,
        session: Session,
        session_id: int,
        status: str = "completed",
        jobs_found: int = 0,
        jobs_new: int = 0,
        jobs_updated: int = 0,
        jobs_failed: int = 0,
        pages_scraped: int = 1,
    ) -> None:
        """Update an ops.scraping_sessions entry upon pipeline completion."""
        session.execute(
            text(
                "UPDATE ops.scraping_sessions SET "
                "finished_at = now(), "
                "status = :status, "
                "jobs_found = :jobs_found, "
                "jobs_new = :jobs_new, "
                "jobs_updated = :jobs_updated, "
                "jobs_failed = :jobs_failed, "
                "pages_scraped = :pages_scraped "
                "WHERE session_id = :session_id"
            ),
            {
                "session_id": session_id,
                "status": status,
                "jobs_found": jobs_found,
                "jobs_new": jobs_new,
                "jobs_updated": jobs_updated,
                "jobs_failed": jobs_failed,
                "pages_scraped": pages_scraped,
            },
        )

    # --- Reference Lookup Helpers ---

    def get_source_id_by_code(self, session: Session, source_code: str = "remoteok") -> int:
        """Look up source_id for a source code (e.g. 'remoteok')."""
        result = session.execute(
            text("SELECT source_id FROM ref.sources WHERE source_code = :source_code"),
            {"source_code": source_code},
        ).scalar()
        if result is None:
            raise RepositoryError(
                f"Source code '{source_code}' not found in ref.sources. Ensure database is seeded."
            )
        return int(result)

    def get_usd_currency_id(self, session: Session) -> int | None:
        """Look up currency_id for 'USD' in ref.currencies."""
        result = session.execute(
            text("SELECT currency_id FROM ref.currencies WHERE iso_code = 'USD'")
        ).scalar()
        return int(result) if result is not None else None

    def get_or_create_company(
        self, session: Session, company_name: str, logo_url: str | None = None
    ) -> int:
        """Resolve company_name to core.companies, creating a record if missing."""
        clean_name = company_name.strip()
        norm_name = clean_name.lower()

        row = session.execute(
            text("SELECT company_id FROM core.companies WHERE normalized_name = :norm_name"),
            {"norm_name": norm_name},
        ).scalar()

        if row is not None:
            return int(row)

        res = session.execute(
            text(
                "INSERT INTO core.companies (company_name, normalized_name, logo_url) "
                "VALUES (:company_name, :norm_name, :logo_url) "
                "RETURNING company_id"
            ),
            {"company_name": clean_name, "norm_name": norm_name, "logo_url": logo_url},
        ).scalar()

        if res is None:
            raise RepositoryError(f"Failed to insert company '{clean_name}'.")
        return int(res)

    # --- Job Ingestion & Upsert ---

    def save_cleaned_job(
        self,
        session: Session,
        job: CleanedJob,
        source_id: int,
        session_id: int | None = None,
    ) -> str:
        """Persist or update a single CleanedJob.

        Returns:
            'inserted' if new record added,
            'updated' if existing record modified,
            'unchanged' if content hash matched existing record.
        """
        company_id = self.get_or_create_company(session, job.company_name, job.company_logo_url)
        # Step 28: resolved inline, not as a deferred batch job -- see
        # this module's docstring and geographic_resolution.py's for why.
        # None if job.location_cleaned is None/blank (no signal to
        # resolve); never fabricated.
        location_id = resolve_and_cache_location(session, job.location_cleaned, source_id)
        content_hash = compute_job_content_hash(
            job_title=job.job_title,
            company_name=job.company_name,
            description_clean=job.description_clean,
            location_cleaned=job.location_cleaned,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
        )

        p_date: date = (
            job.posting_date.date()
            if isinstance(job.posting_date, datetime)
            else (job.posting_date or date.today())
        )
        # closing_date is optional metadata (not every source provides an
        # expiration date -- see CleanedJob.closing_date's docstring), so
        # unlike p_date above it has no "today" fallback: None stays None.
        # It's also deliberately excluded from compute_job_content_hash --
        # a closing-date-only change (e.g. a source extending a posting's
        # expiration) isn't a substantive content change, so it's written
        # on every re-scrape unconditionally below, the same way
        # last_scraped_at always refreshes regardless of whether the hash
        # matched.
        c_date: date | None = (
            job.closing_date.date() if isinstance(job.closing_date, datetime) else job.closing_date
        )

        # Check existing job by (source_id, source_job_id)
        existing = session.execute(
            text(
                "SELECT job_id, posting_date, content_hash FROM core.jobs "
                "WHERE source_id = :source_id AND source_job_id = :source_job_id "
                "ORDER BY posting_date DESC LIMIT 1"
            ),
            {"source_id": source_id, "source_job_id": job.source_job_id},
        ).first()

        usd_currency_id = self.get_usd_currency_id(session)
        normalized_annual_min_usd, normalized_annual_max_usd = normalize_annual_salary(
            job.salary_min,
            job.salary_max,
            currency_iso_code=_ASSUMED_CURRENCY_ISO_CODE,
            pay_period=_ASSUMED_PAY_PERIOD,
        )

        if existing:
            job_id, existing_posting_date, existing_hash = existing
            if existing_hash == content_hash:
                # Mark scraped, no content change
                session.execute(
                    text(
                        "UPDATE core.jobs SET "
                        "last_scraped_at = now(), "
                        "last_scraping_session_id = "
                        "COALESCE(:session_id, last_scraping_session_id), "
                        "closing_date = :closing_date "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "job_id": job_id,
                        "posting_date": existing_posting_date,
                        "session_id": session_id,
                        "closing_date": c_date,
                    },
                )
                return "unchanged"
            else:
                # Content changed -> Update job, description, salary
                session.execute(
                    text(
                        "UPDATE core.jobs SET "
                        "job_title = :job_title, "
                        "company_id = :company_id, "
                        "original_url = :original_url, "
                        "content_hash = :content_hash, "
                        "data_quality_score = :data_quality_score, "
                        "closing_date = :closing_date, "
                        "location_id = :location_id, "
                        "last_scraped_at = now(), "
                        "last_scraping_session_id = "
                        "COALESCE(:session_id, last_scraping_session_id), "
                        "updated_at = now() "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "job_title": job.job_title,
                        "company_id": company_id,
                        "original_url": job.original_url,
                        "content_hash": content_hash,
                        "data_quality_score": job.data_quality_score,
                        "closing_date": c_date,
                        "location_id": location_id,
                        "session_id": session_id,
                        "job_id": job_id,
                        "posting_date": existing_posting_date,
                    },
                )
                session.execute(
                    text(
                        "UPDATE core.job_descriptions SET "
                        "description_clean = :description_clean, "
                        "word_count = :word_count, "
                        "updated_at = now() "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "description_clean": job.description_clean,
                        "word_count": job.word_count,
                        "job_id": job_id,
                        "posting_date": existing_posting_date,
                    },
                )
                # Fetch the current salary snapshot BEFORE overwriting it,
                # so we know whether this change is worth an append to
                # salary.salary_history (see the append condition below).
                existing_salary = session.execute(
                    text(
                        "SELECT salary_min, salary_max FROM salary.job_salaries "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {"job_id": job_id, "posting_date": existing_posting_date},
                ).first()
                existing_salary_min = existing_salary[0] if existing_salary else None
                existing_salary_max = existing_salary[1] if existing_salary else None

                # Append a salary_history row only for a *substantive*
                # change: both the old and new values must be disclosed
                # (non-null) and actually differ. This deliberately skips
                # pure disclosure toggles (e.g. a re-scrape where the
                # salary field simply appeared or disappeared, with no
                # prior/new figure to compare) -- confirmed design
                # decision, not an oversight: a toggle isn't a "the salary
                # changed" event in the sense this table exists to
                # capture, and logging one would clutter the history with
                # noise that doesn't answer "what did the salary trend
                # look like."
                salary_changed = (
                    existing_salary_min is not None
                    and existing_salary_max is not None
                    and job.salary_min is not None
                    and job.salary_max is not None
                    and (existing_salary_min, existing_salary_max)
                    != (job.salary_min, job.salary_max)
                )
                if salary_changed:
                    session.execute(
                        text(
                            "INSERT INTO salary.salary_history "
                            "(job_id, posting_date, observed_at, salary_min, salary_max, "
                            "currency_id, pay_period) "
                            "VALUES (:job_id, :posting_date, now(), :salary_min, :salary_max, "
                            ":currency_id, :pay_period)"
                        ),
                        {
                            "job_id": job_id,
                            "posting_date": existing_posting_date,
                            "salary_min": job.salary_min,
                            "salary_max": job.salary_max,
                            "currency_id": usd_currency_id,
                            "pay_period": _ASSUMED_PAY_PERIOD,
                        },
                    )

                session.execute(
                    text(
                        "UPDATE salary.job_salaries SET "
                        "salary_min = :salary_min, "
                        "salary_max = :salary_max, "
                        "salary_disclosed = :salary_disclosed, "
                        "normalized_annual_min_usd = :normalized_annual_min_usd, "
                        "normalized_annual_max_usd = :normalized_annual_max_usd, "
                        "updated_at = now() "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "salary_min": job.salary_min,
                        "salary_max": job.salary_max,
                        "salary_disclosed": job.salary_disclosed,
                        "normalized_annual_min_usd": normalized_annual_min_usd,
                        "normalized_annual_max_usd": normalized_annual_max_usd,
                        "job_id": job_id,
                        "posting_date": existing_posting_date,
                    },
                )
                return "updated"
        else:
            # Insert NEW job
            job_id = session.execute(
                text(
                    "INSERT INTO core.jobs "
                    "(source_id, source_job_id, original_url, company_id, job_title, "
                    "location_id, posting_date, closing_date, first_scraped_at, last_scraped_at, "
                    "last_scraping_session_id, "
                    "job_status, content_hash, data_quality_score) "
                    "VALUES "
                    "(:source_id, :source_job_id, :original_url, :company_id, :job_title, "
                    ":location_id, :posting_date, :closing_date, now(), now(), :session_id, "
                    "'active', :content_hash, :data_quality_score) "
                    "RETURNING job_id"
                ),
                {
                    "source_id": source_id,
                    "source_job_id": job.source_job_id,
                    "original_url": job.original_url,
                    "company_id": company_id,
                    "job_title": job.job_title,
                    "location_id": location_id,
                    "posting_date": p_date,
                    "closing_date": c_date,
                    "session_id": session_id,
                    "content_hash": content_hash,
                    "data_quality_score": job.data_quality_score,
                },
            ).scalar()

            if job_id is None:
                raise RepositoryError(f"Failed to insert job {job.source_job_id}")

            # Insert job_description
            session.execute(
                text(
                    "INSERT INTO core.job_descriptions "
                    "(job_id, posting_date, description_clean, word_count) "
                    "VALUES (:job_id, :posting_date, :description_clean, :word_count)"
                ),
                {
                    "job_id": job_id,
                    "posting_date": p_date,
                    "description_clean": job.description_clean,
                    "word_count": job.word_count,
                },
            )

            # Insert job_salary
            session.execute(
                text(
                    "INSERT INTO salary.job_salaries "
                    "(job_id, posting_date, salary_min, salary_max, currency_id, "
                    "pay_period, salary_disclosed, normalized_annual_min_usd, "
                    "normalized_annual_max_usd) "
                    "VALUES (:job_id, :posting_date, :salary_min, :salary_max, "
                    ":currency_id, :pay_period, :salary_disclosed, "
                    ":normalized_annual_min_usd, :normalized_annual_max_usd)"
                ),
                {
                    "job_id": job_id,
                    "posting_date": p_date,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "currency_id": usd_currency_id,
                    "pay_period": _ASSUMED_PAY_PERIOD,
                    "salary_disclosed": job.salary_disclosed,
                    "normalized_annual_min_usd": normalized_annual_min_usd,
                    "normalized_annual_max_usd": normalized_annual_max_usd,
                },
            )

            # Insert the Day 1 salary_history row -- every job gets one on
            # insert, not just later changes, so the history table's
            # first entry always reflects what the job actually shipped
            # with (see normalization/salary_standardization.py's module
            # docstring for why this table was previously never written).
            session.execute(
                text(
                    "INSERT INTO salary.salary_history "
                    "(job_id, posting_date, observed_at, salary_min, salary_max, "
                    "currency_id, pay_period) "
                    "VALUES (:job_id, :posting_date, now(), :salary_min, :salary_max, "
                    ":currency_id, :pay_period)"
                ),
                {
                    "job_id": job_id,
                    "posting_date": p_date,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "currency_id": usd_currency_id,
                    "pay_period": _ASSUMED_PAY_PERIOD,
                },
            )

            return "inserted"

    def save_cleaned_jobs(
        self,
        session: Session,
        jobs: list[CleanedJob],
        source_id: int,
        session_id: int | None = None,
    ) -> dict[str, int]:
        """Batch save CleanedJob records.

        Each job's persistence runs inside its own ``SAVEPOINT`` (see
        ``db.transaction.transaction``), NOT directly on the shared
        session. This matters: without it, a single constraint violation
        (e.g. a bad salary range) leaves the underlying PostgreSQL
        transaction aborted, so every subsequent statement in the same
        batch -- other jobs' inserts, and the final
        ``finish_scraping_session`` bookkeeping update -- fails with
        ``InFailedSqlTransaction``, and the whole session then rolls back
        on exit, silently discarding every job in the batch, including
        ones that individually succeeded. This was a real, confirmed
        production incident (a single reversed Remotive salary range
        caused an entire 18-job run to persist zero rows). Wrapping each
        job in its own savepoint confines a failure to that one job:
        the rest of the batch, and the session-level bookkeeping, still
        commit normally.

        Returns:
            Dictionary with keys 'inserted', 'updated', 'unchanged', 'failed'.
        """
        counts = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}

        for job in jobs:
            try:
                with transaction(session):
                    status = self.save_cleaned_job(
                        session=session, job=job, source_id=source_id, session_id=session_id
                    )
                counts[status] += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to persist job {} (source_id={}): {}", job.source_job_id, source_id, exc
                )
                counts["failed"] += 1

        logger.info(
            "Batch persistence complete: {} inserted, {} updated, {} unchanged, {} failed.",
            counts["inserted"],
            counts["updated"],
            counts["unchanged"],
            counts["failed"],
        )
        return counts

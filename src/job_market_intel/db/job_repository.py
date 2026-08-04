"""db.job_repository
=================

Repository implementation for storing, updating, and deduplicating job records
and managing scraping sessions in PostgreSQL.

Supports Step 9 (PostgreSQL Persistence) and Step 10 (Same-Source Duplicate &
Update Detection via SHA-256 content hashing).
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
from typing import TYPE_CHECKING, Any  

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.db.exceptions import RepositoryError
from job_market_intel.db.repository import AbstractRepository

if TYPE_CHECKING:                             # add this block
    from job_market_intel.cleaning.remoteok_cleaner import CleanedRemoteOKJob


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

    model = None  # Uses direct SQL / session queries against defined schema

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
        job: CleanedRemoteOKJob,
        source_id: int,
        session_id: int | None = None,
    ) -> str:
        """Persist or update a single CleanedRemoteOKJob.

        Returns:
            'inserted' if new record added,
            'updated' if existing record modified,
            'unchanged' if content hash matched existing record.
        """
        company_id = self.get_or_create_company(session, job.company_name, job.company_logo_url)
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

        if existing:
            job_id, existing_posting_date, existing_hash = existing
            if existing_hash == content_hash:
                # Mark scraped, no content change
                session.execute(
                    text(
                        "UPDATE core.jobs SET "
                        "last_scraped_at = now(), "
                        "last_scraping_session_id = COALESCE(:session_id, last_scraping_session_id) "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "job_id": job_id,
                        "posting_date": existing_posting_date,
                        "session_id": session_id,
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
                        "last_scraped_at = now(), "
                        "last_scraping_session_id = COALESCE(:session_id, last_scraping_session_id), "
                        "updated_at = now() "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "job_title": job.job_title,
                        "company_id": company_id,
                        "original_url": job.original_url,
                        "content_hash": content_hash,
                        "data_quality_score": job.data_quality_score,
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
                session.execute(
                    text(
                        "UPDATE salary.job_salaries SET "
                        "salary_min = :salary_min, "
                        "salary_max = :salary_max, "
                        "salary_disclosed = :salary_disclosed, "
                        "updated_at = now() "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {
                        "salary_min": job.salary_min,
                        "salary_max": job.salary_max,
                        "salary_disclosed": job.salary_disclosed,
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
                    "posting_date, first_scraped_at, last_scraped_at, last_scraping_session_id, "
                    "job_status, content_hash, data_quality_score) "
                    "VALUES "
                    "(:source_id, :source_job_id, :original_url, :company_id, :job_title, "
                    ":posting_date, now(), now(), :session_id, "
                    "'active', :content_hash, :data_quality_score) "
                    "RETURNING job_id"
                ),
                {
                    "source_id": source_id,
                    "source_job_id": job.source_job_id,
                    "original_url": job.original_url,
                    "company_id": company_id,
                    "job_title": job.job_title,
                    "posting_date": p_date,
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
                    "(job_id, posting_date, salary_min, salary_max, currency_id, pay_period, salary_disclosed) "
                    "VALUES (:job_id, :posting_date, :salary_min, :salary_max, :currency_id, 'yearly', :salary_disclosed)"
                ),
                {
                    "job_id": job_id,
                    "posting_date": p_date,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "currency_id": usd_currency_id,
                    "salary_disclosed": job.salary_disclosed,
                },
            )

            return "inserted"

    def save_cleaned_jobs(
        self,
        session: Session,
        jobs: list[CleanedRemoteOKJob],
        source_id: int,
        session_id: int | None = None,
    ) -> dict[str, int]:
        """Batch save CleanedRemoteOKJob records.

        Returns:
            Dictionary with keys 'inserted', 'updated', 'unchanged', 'failed'.
        """
        counts = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}

        for job in jobs:
            try:
                status = self.save_cleaned_job(
                    session=session, job=job, source_id=source_id, session_id=session_id
                )
                counts[status] += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to persist RemoteOK job {}: {}", job.source_job_id, exc
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

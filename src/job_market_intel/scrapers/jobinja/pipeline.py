"""Automated ETL pipeline for Jobinja.

Same shape as ``scrapers/glints/pipeline.py``: Fetching -> Parsing ->
Batch Validation -> Text Cleaning -> Database Storage & Deduplication.

Unlike Glints, there is no skip-known exclusion: Jobinja's discovery
channel is a numbered listing whose order is trustworthy (see
``client.py``), so a backfill progresses by raising
``JOBINGJA_START_PAGE`` instead of filtering uuids, and CI's daily
window from page 1 naturally covers everything posted since the last
run. Content-hash dedup at persist time absorbs any overlap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.jobinja.client import JobinjaClient
from job_market_intel.scrapers.jobinja.config import JobinjaSettings
from job_market_intel.scrapers.jobinja.parser import JobinjaParser
from job_market_intel.validation import JobinjaBatchValidator, JobinjaValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.jobinja_cleaner import JobinjaCleaner
    from job_market_intel.db.job_repository import JobRepository


class JobinjaPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Jobinja pipeline."""

    raw_count: int = Field(..., description="Total raw job records fetched.")
    parsed_count: int = Field(..., description="Jobs successfully parsed into Pydantic models.")
    validation_passed: bool = Field(..., description="Whether batch validation checks passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted into PostgreSQL.")
    updated_count: int = Field(0, description="Existing jobs updated in PostgreSQL.")
    unchanged_count: int = Field(0, description="Jobs skipped (identical SHA-256 content hash).")
    failed_count: int = Field(0, description="Jobs that failed DB persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions session_id if stored.")
    issues: list[str] = Field(default_factory=list, description="Validation issues, if any.")


class JobinjaPipeline:
    """Automated end-to-end pipeline runner for the Jobinja scraper."""

    def __init__(
        self,
        settings: JobinjaSettings | None = None,
        validation_settings: JobinjaValidationSettings | None = None,
        client: JobinjaClient | None = None,
        parser: JobinjaParser | None = None,
        validator: JobinjaBatchValidator | None = None,
        cleaner: JobinjaCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or JobinjaSettings()
        self.client = client or JobinjaClient(settings=self.settings)
        self.parser = parser or JobinjaParser()
        self.validator = validator or JobinjaBatchValidator(
            settings=validation_settings or JobinjaValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.jobinja_cleaner import JobinjaCleaner

            cleaner = JobinjaCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> JobinjaPipelineRunResult:
        """Run the Jobinja pipeline end-to-end.

        The client raises (``JobinjaError`` family) when discovery or
        every fetch fails, so a non-exception return here always carries
        a real batch — no empty-run special case, unlike Glints'
        skip-known no-op path.
        """
        logger.info("Starting Jobinja automated pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_jobs)
        validation_report = self.validator.validate(raw_jobs, parsed_jobs)
        cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)

        result = JobinjaPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed_jobs),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=validation_report.issues,
        )

        if not store_db:
            logger.info("Pipeline dry-run completed (store_db=False).")
            return result

        if session_override is not None:
            self._persist_with_session(session_override, cleaned_jobs, len(raw_jobs), result)
        else:
            try:
                with get_session() as session:
                    self._persist_with_session(session, cleaned_jobs, len(raw_jobs), result)
            except Exception as exc:
                logger.error("Failed to connect or persist to PostgreSQL database: {}", exc)

        return result

    def _persist_with_session(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: JobinjaPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "jobinja")
        session_id = self.repository.create_scraping_session(
            session, source_id=source_id, trigger_type="manual"
        )
        result.session_id = session_id

        counts = self.repository.save_cleaned_jobs(
            session=session,
            jobs=cleaned_jobs,
            source_id=source_id,
            session_id=session_id,
        )

        result.inserted_count = counts["inserted"]
        result.updated_count = counts["updated"]
        result.unchanged_count = counts["unchanged"]
        result.failed_count = counts["failed"]

        status = "completed" if counts["failed"] == 0 else "partial"
        self.repository.finish_scraping_session(
            session=session,
            session_id=session_id,
            status=status,
            jobs_found=raw_count,
            jobs_new=counts["inserted"],
            jobs_updated=counts["updated"],
            jobs_failed=counts["failed"],
            pages_scraped=1,
        )

"""scrapers.remoteok.pipeline
===========================

Automated ETL pipeline for RemoteOK (Phase 2 Steps 11 & 12).
Orchestrates Fetching -> Parsing -> Batch Validation -> Text Cleaning ->
Database Storage & Deduplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.remoteok.client import RemoteOKClient
from job_market_intel.scrapers.remoteok.config import RemoteOKSettings
from job_market_intel.scrapers.remoteok.parser import RemoteOKParser
from job_market_intel.validation import RemoteOKBatchValidator, RemoteOKValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.remoteok_cleaner import RemoteOKCleaner
    from job_market_intel.db.job_repository import JobRepository


class RemoteOKPipelineRunResult(BaseModel):
    """Execution summary for a single run of the RemoteOK pipeline."""

    raw_count: int = Field(..., description="Total raw JSON job records fetched.")
    parsed_count: int = Field(..., description="Jobs successfully parsed into Pydantic models.")
    validation_passed: bool = Field(..., description="Whether batch validation checks passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted into PostgreSQL.")
    updated_count: int = Field(0, description="Existing jobs updated in PostgreSQL.")
    unchanged_count: int = Field(0, description="Jobs skipped (identical SHA-256 content hash).")
    failed_count: int = Field(0, description="Jobs that failed DB persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions session_id if stored.")
    issues: list[str] = Field(default_factory=list, description="Validation issues, if any.")


class RemoteOKPipeline:
    """Automated end-to-end pipeline runner for RemoteOK scrapers."""

    def __init__(
        self,
        settings: RemoteOKSettings | None = None,
        validation_settings: RemoteOKValidationSettings | None = None,
        client: RemoteOKClient | None = None,
        parser: RemoteOKParser | None = None,
        validator: RemoteOKBatchValidator | None = None,
        cleaner: RemoteOKCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or RemoteOKSettings()
        self.client = client or RemoteOKClient(settings=self.settings)
        self.parser = parser or RemoteOKParser()
        self.validator = validator or RemoteOKBatchValidator(
            settings=validation_settings or RemoteOKValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.remoteok_cleaner import RemoteOKCleaner
            cleaner = RemoteOKCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository
            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> RemoteOKPipelineRunResult:
        """Run the RemoteOK pipeline end-to-end.

        Args:
            store_db: If True, persist cleaned jobs into PostgreSQL.
            session_override: Optional SQLAlchemy Session for testing / custom transaction context.

        Returns:
            RemoteOKPipelineRunResult with execution metrics.
        """
        logger.info("Starting RemoteOK automated pipeline run (store_db={}).", store_db)

        # Step 6: Fetch & Parse
        raw_jobs = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        # Step 7: Batch Validate
        validation_report = self.validator.validate(raw_jobs, parsed_jobs)

        # Step 8: Clean & Normalize
        cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)

        result = RemoteOKPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed_jobs),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=validation_report.issues,
        )

        if not store_db:
            logger.info("Pipeline dry-run completed (store_db=False).")
            return result

        # Steps 9 & 10: PostgreSQL Storage & Deduplication
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
        result: RemoteOKPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "remoteok")
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

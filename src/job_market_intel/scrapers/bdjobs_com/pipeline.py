"""Automated ETL pipeline for Bdjobs.

Same shape as ``scrapers/timesjobs_in/pipeline.py``: Bdjobs' search
endpoint IS a newest-first cursor (capped runs read the head of it), so the
pipeline passes no exclusion set -- content-hash dedup handles overlap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.bdjobs_com.client import BdjobsClient
from job_market_intel.scrapers.bdjobs_com.config import BdjobsSettings
from job_market_intel.scrapers.bdjobs_com.parser import BdjobsParser
from job_market_intel.validation import BdjobsBatchValidator, BdjobsValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.bdjobs_com_cleaner import BdjobsCleaner
    from job_market_intel.db.job_repository import JobRepository


class BdjobsPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Bdjobs pipeline."""

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


class BdjobsPipeline:
    """Automated end-to-end pipeline runner for the Bdjobs scraper."""

    def __init__(
        self,
        settings: BdjobsSettings | None = None,
        validation_settings: BdjobsValidationSettings | None = None,
        client: BdjobsClient | None = None,
        parser: BdjobsParser | None = None,
        validator: BdjobsBatchValidator | None = None,
        cleaner: BdjobsCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or BdjobsSettings()
        self.client = client or BdjobsClient(settings=self.settings)
        self.parser = parser or BdjobsParser()
        self.validator = validator or BdjobsBatchValidator(
            settings=validation_settings or BdjobsValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.bdjobs_com_cleaner import BdjobsCleaner

            cleaner = BdjobsCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> BdjobsPipelineRunResult:
        """Run the Bdjobs pipeline end-to-end.

        Fetching walks the open search cursor (no exclusion -- the client
        raises loudly if the first page yields zero rows, so a "successful"
        empty fetch never reaches persistence).
        """
        logger.info("Starting Bdjobs automated pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()

        if raw_jobs:
            parsed_jobs = self.parser.parse_jobs(raw_jobs)
            validation_report = self.validator.validate(raw_jobs, parsed_jobs)
            cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)
            result = BdjobsPipelineRunResult(
                raw_count=len(raw_jobs),
                parsed_count=len(parsed_jobs),
                validation_passed=validation_report.passed,
                cleaned_count=len(cleaned_jobs),
                issues=validation_report.issues,
            )
        else:
            logger.info("Bdjobs returned no job rows this run; nothing to do.")
            cleaned_jobs = []
            result = BdjobsPipelineRunResult(
                raw_count=0,
                parsed_count=0,
                validation_passed=True,
                cleaned_count=0,
                issues=[],
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
                raise

        return result

    def _persist_with_session(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: BdjobsPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "bdjobs_com")
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

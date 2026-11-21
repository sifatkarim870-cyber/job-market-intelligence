"""Automated ETL pipeline for ANPE Mali.

Same shape as ``scrapers/anpe_bf/pipeline.py``: the WP Job Manager
``job-listings`` endpoint is already newest-first (``orderby=date``), so
the pipeline passes no exclusion set -- content-hash dedup handles overlap
between runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.anpe_mali.client import AnpeMaliClient
from job_market_intel.scrapers.anpe_mali.config import AnpeMaliSettings
from job_market_intel.scrapers.anpe_mali.parser import AnpeMaliParser
from job_market_intel.validation import AnpeMaliBatchValidator, AnpeMaliValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.anpe_mali_cleaner import AnpeMaliCleaner
    from job_market_intel.db.job_repository import JobRepository


class AnpeMaliPipelineRunResult(BaseModel):
    """Execution summary for a single run of the ANPE Mali pipeline."""

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


class AnpeMaliPipeline:
    """Automated end-to-end pipeline runner for the ANPE Mali scraper."""

    def __init__(
        self,
        settings: AnpeMaliSettings | None = None,
        validation_settings: AnpeMaliValidationSettings | None = None,
        client: AnpeMaliClient | None = None,
        parser: AnpeMaliParser | None = None,
        validator: AnpeMaliBatchValidator | None = None,
        cleaner: AnpeMaliCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or AnpeMaliSettings()
        self.client = client or AnpeMaliClient(settings=self.settings)
        self.parser = parser or AnpeMaliParser()
        self.validator = validator or AnpeMaliBatchValidator(
            settings=validation_settings or AnpeMaliValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.anpe_mali_cleaner import AnpeMaliCleaner

            cleaner = AnpeMaliCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> AnpeMaliPipelineRunResult:
        """Run the ANPE Mali pipeline end-to-end."""
        logger.info("Starting ANPE Mali automated pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()

        if raw_jobs:
            parsed_jobs = self.parser.parse_jobs(raw_jobs)
            validation_report = self.validator.validate(raw_jobs, parsed_jobs)
            cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)
            result = AnpeMaliPipelineRunResult(
                raw_count=len(raw_jobs),
                parsed_count=len(parsed_jobs),
                validation_passed=validation_report.passed,
                cleaned_count=len(cleaned_jobs),
                issues=validation_report.issues,
            )
        else:
            logger.info("ANPE Mali returned no listing rows this run; nothing to do.")
            cleaned_jobs = []
            result = AnpeMaliPipelineRunResult(
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
        result: AnpeMaliPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "anpe_mali")
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

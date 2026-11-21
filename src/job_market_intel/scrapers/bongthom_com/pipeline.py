"""Automated ETL pipeline for BongThom.

Same shape as ``scrapers/bdjobs_com/pipeline.py``: BongThom's discovery
endpoint IS a newest-first cursor (capped runs read the head of it), so the
pipeline passes no exclusion set -- content-hash dedup handles overlap
between runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.bongthom_com.client import BongthomClient
from job_market_intel.scrapers.bongthom_com.config import BongthomSettings
from job_market_intel.scrapers.bongthom_com.parser import BongthomParser
from job_market_intel.validation import BongthomBatchValidator, BongthomValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.bongthom_com_cleaner import BongthomCleaner
    from job_market_intel.db.job_repository import JobRepository


class BongthomPipelineRunResult(BaseModel):
    """Execution summary for a single run of the BongThom pipeline."""

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


class BongthomPipeline:
    """Automated end-to-end pipeline runner for the BongThom scraper."""

    def __init__(
        self,
        settings: BongthomSettings | None = None,
        validation_settings: BongthomValidationSettings | None = None,
        client: BongthomClient | None = None,
        parser: BongthomParser | None = None,
        validator: BongthomBatchValidator | None = None,
        cleaner: BongthomCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or BongthomSettings()
        self.client = client or BongthomClient(settings=self.settings)
        self.parser = parser or BongthomParser()
        self.validator = validator or BongthomBatchValidator(
            settings=validation_settings or BongthomValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.bongthom_com_cleaner import BongthomCleaner

            cleaner = BongthomCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> BongthomPipelineRunResult:
        """Run the BongThom pipeline end-to-end.

        Fetching walks the open discovery cursor (no exclusion -- the client
        raises loudly if the first page yields zero rows, so a "successful"
        empty fetch never reaches persistence).
        """
        logger.info("Starting BongThom automated pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()

        if raw_jobs:
            parsed_jobs = self.parser.parse_jobs(raw_jobs)
            validation_report = self.validator.validate(raw_jobs, parsed_jobs)
            cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)
            result = BongthomPipelineRunResult(
                raw_count=len(raw_jobs),
                parsed_count=len(parsed_jobs),
                validation_passed=validation_report.passed,
                cleaned_count=len(cleaned_jobs),
                issues=validation_report.issues,
            )
        else:
            logger.info("BongThom returned no job rows this run; nothing to do.")
            cleaned_jobs = []
            result = BongthomPipelineRunResult(
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
        result: BongthomPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "bongthom_com")
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

"""scrapers.remotive.pipeline
===========================

Automated ETL pipeline for Remotive (Step 18), following the same shape
``scrapers/remoteok/pipeline.py`` and ``scrapers/weworkremotely/pipeline.py``
already established. Orchestrates Fetching -> Parsing -> Batch Validation
-> Text Cleaning -> Database Storage & Deduplication.

Note on ``RemotivePipelineRunResult`` below: every field the same shape
RemoteOK's/WWR's ``PipelineRunResult`` uses, including the mypy call-arg
false positive both of those already carry (no pydantic-mypy plugin
configured — see Step 17b's cleanup notes) on the ``RemotivePipelineRunResult(...)``
construction call below. Left as-is, consistent with the agreed handling
for the other two sources, not a new problem introduced here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.remotive.client import RemotiveClient
from job_market_intel.scrapers.remotive.config import RemotiveSettings
from job_market_intel.scrapers.remotive.parser import RemotiveParser
from job_market_intel.validation import RemotiveBatchValidator, RemotiveValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.remotive_cleaner import RemotiveCleaner
    from job_market_intel.db.job_repository import JobRepository


class RemotivePipelineRunResult(BaseModel):
    """Execution summary for a single run of the Remotive pipeline."""

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


class RemotivePipeline:
    """Automated end-to-end pipeline runner for the Remotive scraper."""

    def __init__(
        self,
        settings: RemotiveSettings | None = None,
        validation_settings: RemotiveValidationSettings | None = None,
        client: RemotiveClient | None = None,
        parser: RemotiveParser | None = None,
        validator: RemotiveBatchValidator | None = None,
        cleaner: RemotiveCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or RemotiveSettings()
        self.client = client or RemotiveClient(settings=self.settings)
        self.parser = parser or RemotiveParser()
        self.validator = validator or RemotiveBatchValidator(
            settings=validation_settings or RemotiveValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.remotive_cleaner import RemotiveCleaner

            cleaner = RemotiveCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> RemotivePipelineRunResult:
        """Run the Remotive pipeline end-to-end.

        Args:
            store_db: If True, persist cleaned jobs into PostgreSQL.
            session_override: Optional SQLAlchemy Session for testing / custom transaction context.

        Returns:
            RemotivePipelineRunResult with execution metrics.
        """
        logger.info("Starting Remotive automated pipeline run (store_db={}).", store_db)

        # Fetch & Parse
        raw_jobs = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        # Batch Validate
        validation_report = self.validator.validate(raw_jobs, parsed_jobs)

        # Clean & Normalize
        cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)

        result = RemotivePipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed_jobs),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=validation_report.issues,
        )

        if not store_db:
            logger.info("Pipeline dry-run completed (store_db=False).")
            return result

        # PostgreSQL Storage & Deduplication
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
        result: RemotivePipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "remotive")
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

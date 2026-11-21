"""Automated ETL pipeline for BLMIS.

Same shape as ``scrapers/bdjobs_com/pipeline.py``: the single jobseeker
page IS the whole inventory (read once per run), so the pipeline passes no
exclusion set -- content-hash dedup handles the overlap between runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.blmis_bt.client import BlmisClient
from job_market_intel.scrapers.blmis_bt.config import BlmisSettings
from job_market_intel.scrapers.blmis_bt.parser import BlmisParser
from job_market_intel.validation import BlmisBatchValidator, BlmisValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.blmis_bt_cleaner import BlmisCleaner
    from job_market_intel.db.job_repository import JobRepository


class BlmisPipelineRunResult(BaseModel):
    """Execution summary for a single run of the BLMIS pipeline."""

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


class BlmisPipeline:
    """Automated end-to-end pipeline runner for the BLMIS scraper."""

    def __init__(
        self,
        settings: BlmisSettings | None = None,
        validation_settings: BlmisValidationSettings | None = None,
        client: BlmisClient | None = None,
        parser: BlmisParser | None = None,
        validator: BlmisBatchValidator | None = None,
        cleaner: BlmisCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or BlmisSettings()
        self.client = client or BlmisClient(settings=self.settings)
        self.parser = parser or BlmisParser()
        self.validator = validator or BlmisBatchValidator(
            settings=validation_settings or BlmisValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.blmis_bt_cleaner import BlmisCleaner

            cleaner = BlmisCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> BlmisPipelineRunResult:
        """Run the BLMIS pipeline end-to-end.

        The client raises loudly if the page yields zero vacancies, so a
        "successful" empty fetch never reaches persistence.
        """
        logger.info("Starting BLMIS automated pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()

        if raw_jobs:
            parsed_jobs = self.parser.parse_jobs(raw_jobs)
            validation_report = self.validator.validate(raw_jobs, parsed_jobs)
            cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)
            result = BlmisPipelineRunResult(
                raw_count=len(raw_jobs),
                parsed_count=len(parsed_jobs),
                validation_passed=validation_report.passed,
                cleaned_count=len(cleaned_jobs),
                issues=validation_report.issues,
            )
        else:
            logger.info("BLMIS returned no job rows this run; nothing to do.")
            cleaned_jobs = []
            result = BlmisPipelineRunResult(
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
        result: BlmisPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "blmis_bt")
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

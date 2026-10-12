"""End-to-end ETL pipeline for the Jobicy feed.

Fetch -> Parse -> Filter -> Validate -> Clean -> Persist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.jobicy.client import JobicyClient
from job_market_intel.scrapers.jobicy.config import JobicySettings
from job_market_intel.scrapers.jobicy.parser import JobicyParser
from job_market_intel.validation.jobicy_validator import (
    JobicyBatchValidator,
    JobicyValidationSettings,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_market_intel.cleaning.jobicy_cleaner import JobicyCleaner
    from job_market_intel.db.job_repository import JobRepository


class JobicyPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Jobicy pipeline."""

    raw_count: int = Field(..., description="Total raw records fetched.")
    parsed_count: int = Field(..., description="Records that passed validation.")
    filtered_count: int = Field(
        default=0, description="Records dropped by the industry focus filter."
    )
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Identical content hash; skipped.")
    failed_count: int = Field(0, description="Jobs that failed persistence.")
    session_id: int | None = Field(None, description="scraping_sessions.session_id.")
    issues: list[str] = Field(default_factory=list, description="Validation issues.")


class JobicyPipeline:
    """Automated end-to-end pipeline runner for the Jobicy feed."""

    def __init__(
        self,
        settings: JobicySettings | None = None,
        validation_settings: JobicyValidationSettings | None = None,
        client: JobicyClient | None = None,
        parser: JobicyParser | None = None,
        validator: JobicyBatchValidator | None = None,
        cleaner: JobicyCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or JobicySettings()
        self.client = client or JobicyClient(settings=self.settings)
        self.parser = parser or JobicyParser()
        self.validator = validator or JobicyBatchValidator(
            settings=validation_settings or JobicyValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.jobicy_cleaner import JobicyCleaner

            cleaner = JobicyCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> JobicyPipelineRunResult:
        logger.info("Starting Jobicy pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        focused = self.parser.filter_focus(parsed_jobs, self.settings.focus_industries)

        # The baseline for the skip rate is the unfiltered PARSED set. Passing
        # the pre-filter list as "raw" made every intentionally-filtered posting
        # look like a parse failure and reported FAILED on a healthy run.
        validation_report = self.validator.validate(
            [j.raw_payload for j in focused], focused
        )

        cleaned_jobs = self.cleaner.clean_jobs(focused)

        cap = self.settings.max_jobs_per_run
        if len(cleaned_jobs) > cap:
            logger.info(
                "Jobicy run cap: keeping {} of {} cleaned jobs (JOBICY_MAX_JOBS_PER_RUN={})",
                cap,
                len(cleaned_jobs),
                cap,
            )
            cleaned_jobs = cleaned_jobs[:cap]

        result = JobicyPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed_jobs),
            filtered_count=len(parsed_jobs) - len(focused),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=list(getattr(validation_report, "issues", []) or []),
        )

        if not store_db:
            logger.info("Jobicy pipeline dry-run complete (store_db=False).")
            return result

        if session_override is not None:
            self._persist(session_override, cleaned_jobs, len(raw_jobs), result)
        else:
            try:
                with get_session() as session:
                    self._persist(session, cleaned_jobs, len(raw_jobs), result)
            except Exception as exc:  # noqa: BLE001
                logger.error("Jobicy failed to connect or persist to the database: {}", exc)

        return result

    def _persist(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: JobicyPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "jobicy")
        session_id = self.repository.create_scraping_session(
            session, source_id=source_id, trigger_type="scheduled"
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

        self.repository.finish_scraping_session(
            session=session,
            session_id=session_id,
            status="completed" if counts["failed"] == 0 else "partial",
            jobs_found=raw_count,
            jobs_new=counts["inserted"],
            jobs_updated=counts["updated"],
            jobs_failed=counts["failed"],
            pages_scraped=1,
        )

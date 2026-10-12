"""End-to-end ETL pipeline for The Muse feed.

Fetch -> Parse -> Drop stale -> Validate -> Clean -> Persist.

The age filter runs BEFORE validation so the health check measures the batch
that is actually about to be stored, and the skip-rate baseline is the
post-filter parsed set: the age filter is intentional narrowing, not data
loss, and reporting it as a parse failure is how a health check gets ignored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.themuse.client import ThemuseClient
from job_market_intel.scrapers.themuse.config import ThemuseSettings
from job_market_intel.scrapers.themuse.parser import ThemuseParser
from job_market_intel.validation.themuse_validator import (
    ThemuseBatchValidator,
    ThemuseValidationSettings,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_market_intel.cleaning.themuse_cleaner import ThemuseCleaner
    from job_market_intel.db.job_repository import JobRepository


class ThemusePipelineRunResult(BaseModel):
    """Execution summary for a single run of The Muse."""

    raw_count: int = Field(..., description="Total raw records fetched.")
    parsed_count: int = Field(..., description="Records that passed model validation.")
    stale_count: int = Field(
        default=0, description="Records dropped as older than max_age_days."
    )
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Identical content hash; skipped.")
    failed_count: int = Field(0, description="Jobs that failed persistence.")
    session_id: int | None = Field(None, description="scraping_sessions.session_id.")
    issues: list[str] = Field(default_factory=list, description="Validation issues.")


class ThemusePipeline:
    """Automated end-to-end pipeline runner for The Muse."""

    def __init__(
        self,
        settings: ThemuseSettings | None = None,
        validation_settings: ThemuseValidationSettings | None = None,
        client: ThemuseClient | None = None,
        parser: ThemuseParser | None = None,
        validator: ThemuseBatchValidator | None = None,
        cleaner: ThemuseCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or ThemuseSettings()
        self.client = client or ThemuseClient(settings=self.settings)
        self.parser = parser or ThemuseParser()
        self.validator = validator or ThemuseBatchValidator(
            settings=validation_settings or ThemuseValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.themuse_cleaner import ThemuseCleaner

            cleaner = ThemuseCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> ThemusePipelineRunResult:
        logger.info("Starting The Muse pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        fresh = self.parser.drop_stale(parsed_jobs, self.settings.max_age_days)

        validation_report = self.validator.validate(
            [j.raw_payload for j in fresh], fresh
        )

        cleaned_jobs = self.cleaner.clean_jobs(fresh)

        cap = self.settings.max_jobs_per_run
        if len(cleaned_jobs) > cap:
            logger.info(
                "The Muse run cap: keeping {} of {} cleaned jobs (THEMUSE_MAX_JOBS_PER_RUN={})",
                cap,
                len(cleaned_jobs),
                cap,
            )
            cleaned_jobs = cleaned_jobs[:cap]

        result = ThemusePipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed_jobs),
            stale_count=len(parsed_jobs) - len(fresh),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=list(getattr(validation_report, "issues", []) or []),
        )

        if not store_db:
            logger.info("The Muse pipeline dry-run complete (store_db=False).")
            return result

        if session_override is not None:
            self._persist(session_override, cleaned_jobs, len(raw_jobs), result)
        else:
            try:
                with get_session() as session:
                    self._persist(session, cleaned_jobs, len(raw_jobs), result)
            except Exception as exc:  # noqa: BLE001
                logger.error("The Muse failed to connect or persist to the database: {}", exc)

        return result

    def _persist(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: ThemusePipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "themuse")
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
            pages_scraped=self.settings.max_pages_per_run,
        )

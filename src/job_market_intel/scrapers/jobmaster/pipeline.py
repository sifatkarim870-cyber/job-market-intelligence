"""Automated ETL pipeline for JobMaster.

Same shape as ``scrapers/irantalent/pipeline.py``: Fetching -> Parsing ->
Batch Validation -> Text Cleaning -> Database Storage & Deduplication,
including the skip-known discovery wiring (the anonymous window is
unordered — every run re-visits the same filter cells — so *only* the
known-id exclusion advances new fetches).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.jobmaster.client import JobmasterClient
from job_market_intel.scrapers.jobmaster.config import JobmasterSettings
from job_market_intel.scrapers.jobmaster.parser import JobmasterParser
from job_market_intel.validation import JobmasterBatchValidator, JobmasterValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.jobmaster_cleaner import JobmasterCleaner
    from job_market_intel.db.job_repository import JobRepository


class JobmasterPipelineRunResult(BaseModel):
    """Execution summary for a single run of the JobMaster pipeline."""

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


class JobmasterPipeline:
    """Automated end-to-end pipeline runner for the JobMaster scraper."""

    def __init__(
        self,
        settings: JobmasterSettings | None = None,
        validation_settings: JobmasterValidationSettings | None = None,
        client: JobmasterClient | None = None,
        parser: JobmasterParser | None = None,
        validator: JobmasterBatchValidator | None = None,
        cleaner: JobmasterCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or JobmasterSettings()
        self.client = client or JobmasterClient(settings=self.settings)
        self.parser = parser or JobmasterParser()
        self.validator = validator or JobmasterBatchValidator(
            settings=validation_settings or JobmasterValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.jobmaster_cleaner import JobmasterCleaner

            cleaner = JobmasterCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> JobmasterPipelineRunResult:
        """Run the pipeline end-to-end.

        Skip-known exclusion loads stored source_job_ids and passes them
        to the client first; if that lookup fails the run proceeds
        without the exclusion (unbounded but *bounded by the discovery
        budget* regardless) — a database problem should surface at
        persistence, not silently empty the fetch.

        An all-known run yields zero detail fetches on purpose: a
        successful no-op that still records an honest scraping session.
        """
        logger.info("Starting JobMaster automated pipeline run (store_db={}).", store_db)

        exclude_ids = self._load_known_ids(session_override) if store_db else None
        raw_jobs = self.client.fetch_raw_jobs(exclude_ids=exclude_ids)

        if raw_jobs:
            parsed_jobs = self.parser.parse_jobs(raw_jobs)
            validation_report = self.validator.validate(raw_jobs, parsed_jobs)
            cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)
            result = JobmasterPipelineRunResult(
                raw_count=len(raw_jobs),
                parsed_count=len(parsed_jobs),
                validation_passed=validation_report.passed,
                cleaned_count=len(cleaned_jobs),
                issues=validation_report.issues,
            )
        else:
            logger.info(
                "No unseen JobMaster jobs this run ({} known excluded); nothing to do.",
                len(exclude_ids or ()),
            )
            cleaned_jobs = []
            result = JobmasterPipelineRunResult(
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

        return result

    def _load_known_ids(self, session_override: Any | None) -> set[str] | None:
        """Already-stored jobmaster job ids for skip-known selection.

        Returns ``None`` (no exclusion — discovery caps still bound the
        run) when the lookup cannot run, so a database outage degrades
        fetch behavior instead of skipping the scrape entirely.
        """
        try:
            if session_override is not None:
                return self._known_ids_in(session_override)
            with get_session() as session:
                return self._known_ids_in(session)
        except Exception as exc:  # noqa: BLE001 — degradation, not silence
            logger.warning(
                "Could not load known JobMaster source_job_ids; proceeding "
                "without skip-known exclusion: {}",
                exc,
            )
            return None

    def _known_ids_in(self, session: Any) -> set[str]:
        source_id = self.repository.get_source_id_by_code(session, "jobmaster")
        return self.repository.get_all_source_job_ids(session, source_id)

    def _persist_with_session(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: JobmasterPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "jobmaster")
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

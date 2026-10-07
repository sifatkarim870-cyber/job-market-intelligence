"""Automated ETL pipeline for Jobvision.

Same shape as ``scrapers/glints/pipeline.py``: Fetching -> Parsing ->
Batch Validation -> Text Cleaning -> Database Storage & Deduplication,
including the skip-known discovery wiring (Jobvision's sitemap is not
newest-first, so *only* exclusion makes capped runs progress deeper).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.jobvision.client import JobvisionClient
from job_market_intel.scrapers.jobvision.config import JobvisionSettings
from job_market_intel.scrapers.jobvision.parser import JobvisionParser
from job_market_intel.validation import JobvisionBatchValidator, JobvisionValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.jobvision_cleaner import JobvisionCleaner
    from job_market_intel.db.job_repository import JobRepository


class JobvisionPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Jobvision pipeline."""

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


class JobvisionPipeline:
    """Automated end-to-end pipeline runner for the Jobvision scraper."""

    def __init__(
        self,
        settings: JobvisionSettings | None = None,
        validation_settings: JobvisionValidationSettings | None = None,
        client: JobvisionClient | None = None,
        parser: JobvisionParser | None = None,
        validator: JobvisionBatchValidator | None = None,
        cleaner: "JobvisionCleaner | None" = None,
        repository: "JobRepository | None" = None,
    ) -> None:
        self.settings = settings or JobvisionSettings()
        self.client = client or JobvisionClient(settings=self.settings)
        self.parser = parser or JobvisionParser()
        self.validator = validator or JobvisionBatchValidator(
            settings=validation_settings or JobvisionValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.jobvision_cleaner import JobvisionCleaner

            cleaner = JobvisionCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> JobvisionPipelineRunResult:
        """Run the Jobvision pipeline end-to-end.

        When storing, the run first loads the source's already-stored
        ``source_job_ids`` and passes them to the client as an
        exclusion (see ``JobRepository.get_all_source_job_ids``), so a
        capped window fetches only *unseen* jobs — essential for this
        source because the sitemap has no newest-first ordering. If
        that lookup fails, the run proceeds without the exclusion
        (head-of-sitemap window) rather than skipping the scrape: a
        database problem should surface at persistence, not silently
        suppress fetching.

        A run where everything is already known fetches zero jobs. That
        is a successful no-op, not a validation failure: there is no
        batch to validate or clean, so the result reports an empty
        passing batch, and (when storing) an honest zero-jobs scraping
        session is still recorded.
        """
        logger.info("Starting Jobvision automated pipeline run (store_db={}).", store_db)

        exclude_ids = self._load_known_ids(session_override) if store_db else None
        raw_jobs = self.client.fetch_raw_jobs(exclude_ids=exclude_ids)

        if raw_jobs:
            parsed_jobs = self.parser.parse_jobs(raw_jobs)
            validation_report = self.validator.validate(raw_jobs, parsed_jobs)
            cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)
            result = JobvisionPipelineRunResult(
                raw_count=len(raw_jobs),
                parsed_count=len(parsed_jobs),
                validation_passed=validation_report.passed,
                cleaned_count=len(cleaned_jobs),
                issues=validation_report.issues,
            )
        else:
            logger.info(
                "No unseen Jobvision jobs this run ({} known excluded); nothing to do.",
                len(exclude_ids or ()),
            )
            cleaned_jobs = []
            result = JobvisionPipelineRunResult(
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
        """Already-stored jobvision job ids for skip-known selection.

        Returns ``None`` (no exclusion — head-of-sitemap window) when
        the lookup cannot run, so a database outage degrades to the
        plain fetch behavior and still fails visibly at persistence,
        instead of turning into "no scrape at all".
        """
        try:
            if session_override is not None:
                return self._known_ids_in(session_override)
            with get_session() as session:
                return self._known_ids_in(session)
        except Exception as exc:  # noqa: BLE001 — degradation, not silence
            logger.warning(
                "Could not load known Jobvision source_job_ids; proceeding "
                "without skip-known exclusion: {}",
                exc,
            )
            return None

    def _known_ids_in(self, session: Any) -> set[str]:
        source_id = self.repository.get_source_id_by_code(session, "jobvision")
        return self.repository.get_all_source_job_ids(session, source_id)

    def _persist_with_session(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: JobvisionPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "jobvision")
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

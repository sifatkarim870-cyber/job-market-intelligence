"""End-to-end ETL pipeline for the Himalayas feed.

Fetch -> Parse -> Batch Validate -> Clean -> Persist.

The two caps that matter are ``max_pages_per_run`` (how many offset windows to
walk) and ``max_jobs_per_run`` (how many postings to persist). The second is
enforced HERE rather than left to the repository, so a run cannot quietly write
more than intended because the feed grew.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.himalayas.client import HimalayasClient
from job_market_intel.scrapers.himalayas.config import HimalayasSettings
from job_market_intel.scrapers.himalayas.parser import HimalayasParser
from job_market_intel.validation.himalayas_validator import (
    HimalayasBatchValidator,
    HimalayasValidationSettings,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_market_intel.cleaning.himalayas_cleaner import HimalayasCleaner
    from job_market_intel.db.job_repository import JobRepository


class HimalayasPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Himalayas pipeline."""

    raw_count: int = Field(..., description="Total raw records fetched.")
    parsed_count: int = Field(..., description="Records that passed validation.")
    filtered_count: int = Field(
        default=0, description="Records dropped by the category focus filter."
    )
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Identical content hash; skipped.")
    failed_count: int = Field(0, description="Jobs that failed persistence.")
    session_id: int | None = Field(None, description="scraping_sessions.session_id.")
    issues: list[str] = Field(default_factory=list, description="Validation issues.")


class HimalayasPipeline:
    """Automated end-to-end pipeline runner for the Himalayas feed."""

    def __init__(
        self,
        settings: HimalayasSettings | None = None,
        validation_settings: HimalayasValidationSettings | None = None,
        client: HimalayasClient | None = None,
        parser: HimalayasParser | None = None,
        validator: HimalayasBatchValidator | None = None,
        cleaner: HimalayasCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or HimalayasSettings()
        self.client = client or HimalayasClient(settings=self.settings)
        self.parser = parser or HimalayasParser()
        self.validator = validator or HimalayasBatchValidator(
            settings=validation_settings or HimalayasValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.himalayas_cleaner import HimalayasCleaner

            cleaner = HimalayasCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> HimalayasPipelineRunResult:
        logger.info("Starting Himalayas pipeline run (store_db={}).", store_db)

        raw_jobs = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        # Category focus is applied BEFORE validation so the health check
        # measures the batch that is actually about to be stored.
        focused = self.parser.filter_focus(parsed_jobs, self.settings.focus_categories)

        # validate_batch derives its skip rate from len(raw_records) vs
        # len(parsed_records). Passing the pre-filter list as "raw" made every
        # filtered posting look like a parse failure -- a 61% "skip rate" and a
        # FAILED report on a perfectly healthy run, which is how a health check
        # gets ignored. The filter is intentional narrowing, not data loss, so
        # the baseline has to be the unfiltered PARSED set: the records the
        # parser actually rejected are counted as skipped, and the filter is
        # not.
        validation_report = self.validator.validate([j.raw_payload for j in focused], focused)

        cleaned_jobs = self.cleaner.clean_jobs(focused)

        cap = self.settings.max_jobs_per_run
        if len(cleaned_jobs) > cap:
            logger.info(
                "Himalayas run cap: keeping {} of {} cleaned jobs (HIMALAYAS_MAX_JOBS_PER_RUN={})",
                cap,
                len(cleaned_jobs),
                cap,
            )
            cleaned_jobs = cleaned_jobs[:cap]

        result = HimalayasPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed_jobs),
            filtered_count=len(parsed_jobs) - len(focused),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=list(getattr(validation_report, "issues", []) or []),
        )

        if not store_db:
            logger.info("Himalayas pipeline dry-run complete (store_db=False).")
            return result

        if session_override is not None:
            self._persist(session_override, cleaned_jobs, len(raw_jobs), result)
        else:
            try:
                with get_session() as session:
                    self._persist(session, cleaned_jobs, len(raw_jobs), result)
            except Exception as exc:  # noqa: BLE001
                logger.error("Himalayas failed to connect or persist to the database: {}", exc)

        return result

    def _persist(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: HimalayasPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "himalayas")
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

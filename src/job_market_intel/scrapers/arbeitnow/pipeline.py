"""scrapers.arbeitnow.pipeline
============================

Automated ETL pipeline for Arbeitnow, following the shape
``scrapers/remotive/pipeline.py`` and ``scrapers/remoteok/pipeline.py`` already
established: Fetching -> Parsing -> Batch Validation -> Text Cleaning ->
Database Storage & Deduplication.

Arbeitnow is a single-endpoint source (one JSON response holds the whole active
listing), so unlike Greenhouse there is no per-board failure accounting -- a
failure here is systemic and is raised, not collected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.arbeitnow.client import ArbeitnowClient
from job_market_intel.scrapers.arbeitnow.config import ArbeitnowSettings
from job_market_intel.scrapers.arbeitnow.parser import ArbeitnowParser
from job_market_intel.validation.arbeitnow_validator import (
    ArbeitnowBatchValidator,
    ArbeitnowValidationSettings,
)

# Imported lazily inside run(): the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here makes that a
# circular import. Same reason the other pipelines use TYPE_CHECKING blocks.
ArbeitnowCleaner = None

if TYPE_CHECKING:
    pass


class ArbeitnowPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Arbeitnow pipeline."""

    raw_count: int = Field(..., description="Total raw JSON job records fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Skipped (identical content hash).")
    failed_count: int = Field(0, description="Records that failed persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions id.")
    issues: list[str] = Field(default_factory=list)


class ArbeitnowPipeline:
    """Automated end-to-end pipeline runner for Arbeitnow."""

    def __init__(
        self,
        settings: ArbeitnowSettings | None = None,
        validation_settings: ArbeitnowValidationSettings | None = None,
        client: ArbeitnowClient | None = None,
        parser: ArbeitnowParser | None = None,
        validator: ArbeitnowBatchValidator | None = None,
        cleaner: ArbeitnowCleaner | None = None,
        source_code: str = "arbeitnow",
    ) -> None:
        self._settings = settings or ArbeitnowSettings()
        self._validation_settings = validation_settings
        self._client = client or ArbeitnowClient(self._settings)
        self._parser = parser or ArbeitnowParser()
        self._validator = validator or ArbeitnowBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            # Lazy import -- see the module-level note about the cycle.
            from job_market_intel.cleaning.arbeitnow_cleaner import (
                ArbeitnowCleaner as _Cleaner,
            )

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> ArbeitnowPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Arbeitnow pipeline (store_db={}).", store_db)

        raw_jobs = self._client.fetch_raw_jobs()
        parsed, parse_issues = self._parser.parse_jobs(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = ArbeitnowPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=bool(getattr(report, "validation_passed", True)),
            cleaned_count=len(cleaned),
            issues=list(parse_issues) + list(getattr(report, "issues", []) or []),
        )

        if not store_db:
            logger.info("--no-db: skipping persistence")
            return result

        # get_session() is a context-manager generator yielding one Session,
        # NOT a sessionmaker -- calling it as a factory raises
        # "'bool' object is not callable".
        with get_session() as session:
            repo: Any = JobRepository()
            # Resolved by source_code, never hardcoded: source_id is a
            # per-database sequence value and 1 is remoteok on this database
            # and something else entirely on another.
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": self._source_code},
            ).scalar()
            if source_id is None:
                raise RuntimeError(
                    f"ref.sources has no row with source_code={self._source_code!r}. "
                    "Run the seed (python -m seed.run_all) before scraping."
                )
            session_id: int | None = None
            for job in cleaned:
                try:
                    outcome = repo.save_cleaned_job(
                        session, job, source_id=int(source_id), session_id=session_id
                    )
                    if outcome == "inserted":
                        result.inserted_count += 1
                    elif outcome == "updated":
                        result.updated_count += 1
                    else:
                        result.unchanged_count += 1
                except Exception as exc:  # noqa: BLE001 - one row must not stop the batch
                    result.failed_count += 1
                    logger.warning("failed to persist Arbeitnow job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "Arbeitnow run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

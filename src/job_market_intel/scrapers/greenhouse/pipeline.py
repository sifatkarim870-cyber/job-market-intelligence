"""scrapers.greenhouse.pipeline
===============================

Automated ETL pipeline for Greenhouse boards, following the shape
``scrapers/remotive/pipeline.py`` and ``scrapers/remoteok/pipeline.py``
already established: Fetching -> Parsing -> Batch Validation -> Text Cleaning
-> Database Storage & Deduplication.

One structural difference from every other source here, and it is the reason
this source is worth building: a single run walks a LIST of company boards
rather than one endpoint. That is reflected in the result object --
``board_failures`` is first-class, because "3 of 4 boards failed" is the single
most useful thing to know after a run, and flattening it into a bare exception
would hide exactly the partial-failure case that is normal here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.greenhouse.client import GreenhouseClient
from job_market_intel.scrapers.greenhouse.config import GreenhouseSettings
from job_market_intel.scrapers.greenhouse.parser import GreenhouseParser
from job_market_intel.validation.greenhouse_validator import (
    GreenhouseBatchValidator,
    GreenhouseValidationSettings,
)

# Imported lazily inside run(): the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here makes that a
# circular import. Same reason the other pipelines use TYPE_CHECKING blocks.
GreenhouseCleaner = None

if TYPE_CHECKING:
    pass


class GreenhousePipelineRunResult(BaseModel):
    """Execution summary for a single run of the Greenhouse pipeline."""

    raw_count: int = Field(..., description="Total raw JSON records fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Skipped (identical content hash).")
    failed_count: int = Field(0, description="Records that failed persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions id.")
    boards_attempted: int = Field(0, description="Company boards requested.")
    boards_failed: int = Field(0, description="Boards that could not be read.")
    board_failures: dict[str, str] = Field(
        default_factory=dict, description="slug -> failure reason."
    )
    issues: list[str] = Field(default_factory=list)


class GreenhousePipeline:
    """Automated end-to-end pipeline runner for Greenhouse boards."""

    def __init__(
        self,
        settings: GreenhouseSettings | None = None,
        validation_settings: GreenhouseValidationSettings | None = None,
        client: GreenhouseClient | None = None,
        parser: GreenhouseParser | None = None,
        validator: GreenhouseBatchValidator | None = None,
        cleaner: GreenhouseCleaner | None = None,
        source_code: str = "greenhouse",
    ) -> None:
        self._settings = settings or GreenhouseSettings()
        self._source_code = source_code
        self._validation_settings = validation_settings
        self._client = client or GreenhouseClient(self._settings)
        self._parser = parser or GreenhouseParser()
        self._validator = validator or GreenhouseBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            # Lazy import -- see the module-level note about the cycle.
            from job_market_intel.cleaning.greenhouse_cleaner import (
                GreenhouseCleaner as _Cleaner,
            )

            self._cleaner = _Cleaner()

    def run(self, *, store_db: bool = True) -> GreenhousePipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info(
            "Starting Greenhouse pipeline over {} board(s) (store_db={})",
            len(self._settings.company_slugs),
            store_db,
        )

        raw_jobs, board_failures = self._client.fetch_all()
        parsed, parse_issues = self._parser.parse_jobs(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        issues = list(parse_issues) + list(getattr(report, "issues", []) or [])
        result = GreenhousePipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=bool(getattr(report, "validation_passed", True)),
            cleaned_count=len(cleaned),
            boards_attempted=len(self._settings.company_slugs),
            boards_failed=len(board_failures),
            board_failures=board_failures,
            issues=issues,
        )

        if not store_db:
            logger.info("--no-db: skipping persistence")
            return result

        # get_session() is a context-manager generator yielding one Session, NOT a
        # sessionmaker -- calling it as a factory raises "'bool' object is not
        # callable".
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
                    logger.warning(
                        "failed to persist Greenhouse job {}: {}", job.source_job_id, exc
                    )
            session.commit()

        logger.info(
            "Greenhouse run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

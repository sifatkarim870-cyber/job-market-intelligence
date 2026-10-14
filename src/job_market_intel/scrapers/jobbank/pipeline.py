"""scrapers.jobbank.pipeline
============================

Automated ETL pipeline for Job Bank Canada: Fetching -> Parsing -> Batch
Validation -> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.arbeitnow/pipeline.py`` establishes. The one
structural difference is failure accounting: Job Bank walks many search terms
and fetches one HTTP request per posting, so a single posting or a single term
can fail without the run being systemic. Failures are therefore collected and
logged, not raised -- the same reasoning Greenhouse uses, at a different
granularity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.jobbank.client import JobBankClient
from job_market_intel.scrapers.jobbank.config import JobBankSettings
from job_market_intel.scrapers.jobbank.parser import JobBankParser
from job_market_intel.validation.jobbank_validator import (
    JobBankBatchValidator,
    JobBankValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
JobBankCleaner = None

if TYPE_CHECKING:
    pass


class JobBankPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Job Bank pipeline."""

    raw_count: int = Field(..., description="Posting detail pages fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Skipped (identical content hash).")
    failed_count: int = Field(0, description="Records that failed persistence.")
    fetch_failures: int = Field(0, description="Postings or search terms that failed during fetch.")
    session_id: int | None = Field(None, description="ops.scraping_sessions id.")
    issues: list[str] = Field(default_factory=list)


class JobBankPipeline:
    """Automated end-to-end pipeline runner for Job Bank Canada."""

    def __init__(
        self,
        settings: JobBankSettings | None = None,
        validation_settings: JobBankValidationSettings | None = None,
        client: JobBankClient | None = None,
        parser: JobBankParser | None = None,
        validator: JobBankBatchValidator | None = None,
        cleaner: JobBankCleaner | None = None,
        source_code: str = "jobbank",
    ) -> None:
        self._settings = settings or JobBankSettings()
        self._validation_settings = validation_settings
        self._client = client or JobBankClient(self._settings)
        self._parser = parser or JobBankParser()
        self._validator = validator or JobBankBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.jobbank_cleaner import JobBankCleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> JobBankPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Job Bank pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/term fetch failure(s) during the Job Bank run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = JobBankPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=bool(getattr(report, "validation_passed", True)),
            cleaned_count=len(cleaned),
            fetch_failures=len(fetch_failures),
            issues=list(parse_issues) + list(getattr(report, "issues", []) or []),
        )

        if not store_db:
            logger.info("--no-db: skipping persistence")
            return result

        # get_session() is a context-manager generator yielding one Session,
        # NOT a sessionmaker.
        with get_session() as session:
            repo: Any = JobRepository()
            # Resolved by source_code, never hardcoded: source_id is a
            # per-database sequence value.
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": self._source_code},
            ).scalar()
            if source_id is None:
                raise RuntimeError(
                    f"ref.sources has no row with source_code={self._source_code!r}. "
                    "Run the seed (python -m seed.run_all) and "
                    "scripts/register_source.py jobbank before scraping."
                )
            for job in cleaned:
                # Each row gets its own savepoint. Without one, the first
                # constraint violation aborts the enclosing transaction and
                # every later row fails with InFailedSqlTransaction -- so one
                # bad posting silently costs the whole batch. That is exactly
                # what the first real run did here: 0 inserted, 30 failed, all
                # traceable to a single bad pay_period value.
                try:
                    with transaction(session):
                        outcome = repo.save_cleaned_job(session, job, source_id=int(source_id))
                    if outcome == "inserted":
                        result.inserted_count += 1
                    elif outcome == "updated":
                        result.updated_count += 1
                    else:
                        result.unchanged_count += 1
                except Exception as exc:  # noqa: BLE001 - one row must not stop the batch
                    result.failed_count += 1
                    logger.warning("failed to persist Job Bank job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "Job Bank run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

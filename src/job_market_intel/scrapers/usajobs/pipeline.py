"""scrapers.usajobs.pipeline
=============================

Automated ETL pipeline for USAJOBS (the US federal job board): Fetching ->
Parsing -> Batch Validation -> Text Cleaning -> Database Storage &
Deduplication.

Follows the shape ``scrapers.jobbank/pipeline.py`` establishes, including the
per-row savepoint: USAJOBS carries a pay-period code that has to be translated
into the schema's five-value vocabulary, and a single mistranslation aborts the
enclosing transaction so that every later row fails too.

The one source-specific concern is the API key. It is a data.gov credential
with a hard hourly budget, so a missing key is reported as an auth error at the
start of the run rather than surfacing later as "0 jobs scraped" alongside an
otherwise healthy report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.usajobs.client import USAJobsClient
from job_market_intel.scrapers.usajobs.config import USAJobsSettings
from job_market_intel.scrapers.usajobs.exceptions import USAJobsAuthError
from job_market_intel.scrapers.usajobs.parser import USAJobsParser
from job_market_intel.validation.usajobs_validator import (
    USAJobsBatchValidator,
    USAJobsValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
USAJobsCleaner = None

if TYPE_CHECKING:
    pass


class USAJobsPipelineRunResult(BaseModel):
    """Execution summary for a single run of the USAJOBS pipeline."""

    raw_count: int = Field(..., description="Posting descriptors fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Skipped (identical content hash).")
    failed_count: int = Field(0, description="Records that failed persistence.")
    fetch_failures: int = Field(0, description="Postings or keywords that failed during fetch.")
    session_id: int | None = Field(None, description="ops.scraping_sessions id.")
    issues: list[str] = Field(default_factory=list)


class USAJobsPipeline:
    """Automated end-to-end pipeline runner for USAJOBS."""

    def __init__(
        self,
        settings: USAJobsSettings | None = None,
        validation_settings: USAJobsValidationSettings | None = None,
        client: USAJobsClient | None = None,
        parser: USAJobsParser | None = None,
        validator: USAJobsBatchValidator | None = None,
        cleaner: USAJobsCleaner | None = None,
        source_code: str = "usajobs",
    ) -> None:
        self._settings = settings or USAJobsSettings()
        self._validation_settings = validation_settings
        self._client = client or USAJobsClient(self._settings)
        self._parser = parser or USAJobsParser()
        self._validator = validator or USAJobsBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.usajobs_cleaner import USAJobsCleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> USAJobsPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting USAJOBS pipeline (store_db={}).", store_db)

        if not self._settings.api_key:
            # Fail loudly and immediately. Without this the run "succeeds" with
            # zero jobs and every downstream report looks healthy.
            raise USAJobsAuthError(
                "no USAJOBS API key configured, so the run would persist "
                "nothing while reporting success. Set USAJOBS_API_KEY, or point "
                "USAJOBS_API_KEY_FILE at a file containing it. Free keys come "
                "from https://developer.usajobs.gov/."
            )

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/keyword fetch failure(s) during the USAJOBS run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = USAJobsPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            # ``report.passed``, not ``getattr(report, "validation_passed", True)``:
            # BatchValidationReport has no attribute by that name, so the getattr
            # fallback silently returned True and every run reported PASSED.
            validation_passed=report.passed,
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
                    "scripts/register_source.py usajobs before scraping."
                )
            for job in cleaned:
                # Per-row savepoint: a pay_period outside
                # hourly/daily/weekly/monthly/yearly violates
                # ck_job_salaries_pay_period, which aborts the enclosing
                # transaction, so without savepoints one bad posting costs the
                # whole batch as InFailedSqlTransaction.
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
                    logger.warning("failed to persist USAJOBS job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "USAJOBS run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

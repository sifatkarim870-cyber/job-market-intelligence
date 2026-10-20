"""Automated ETL pipeline for JobMail (South Africa). Plain HTTP -- no browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.jobmail.client import JobMailClient
from job_market_intel.scrapers.jobmail.config import JobMailSettings
from job_market_intel.scrapers.jobmail.parser import JobMailParser
from job_market_intel.validation.jobmail_validator import JobMailBatchValidator

if TYPE_CHECKING:
    from job_market_intel.cleaning.jobmail_cleaner import JobMailCleaner
    from job_market_intel.validation.jobmail_validator import JobMailValidationSettings


class JobMailPipelineRunResult(BaseModel):
    raw_count: int = Field(..., description="Postings fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    with_salary: int = Field(default=0, description="Postings carrying a pay figure.")
    salary_undisclosed: int = Field(
        default=0, description="Postings publishing a salary but not a figure."
    )
    with_city: int = Field(default=0, description="Postings whose location names a city.")
    with_province: int = Field(default=0, description="Postings whose location names a province.")
    inserted_count: int = Field(default=0, description="New jobs inserted.")
    updated_count: int = Field(default=0, description="Existing jobs updated.")
    unchanged_count: int = Field(default=0, description="Skipped (identical content hash).")
    failed_count: int = Field(default=0, description="Records that failed persistence.")
    fetch_failures: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)


class JobMailPipeline:
    def __init__(
        self,
        settings: JobMailSettings | None = None,
        validation_settings: JobMailValidationSettings | None = None,
        client: JobMailClient | None = None,
        parser: JobMailParser | None = None,
        validator: JobMailBatchValidator | None = None,
        cleaner: JobMailCleaner | None = None,
        source_code: str = "jobmail",
    ) -> None:
        self._settings = settings or JobMailSettings()
        self._validation_settings = validation_settings
        self._client = client or JobMailClient(self._settings)
        self._parser = parser or JobMailParser()
        self._validator = validator or JobMailBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.jobmail_cleaner import JobMailCleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> JobMailPipelineRunResult:
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting JobMail pipeline (store_db={}).", store_db)
        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the jobmail run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )
        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)
        result = JobMailPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=report.passed,
            cleaned_count=len(cleaned),
            with_salary=sum(
                1 for j in parsed if j.salary_min is not None or j.salary_max is not None
            ),
            salary_undisclosed=sum(1 for j in parsed if j.salary_undisclosed),
            with_city=sum(1 for j in parsed if j.locality and j.locality != j.region),
            with_province=sum(1 for j in parsed if j.region),
            fetch_failures=len(fetch_failures),
            issues=list(parse_issues) + list(getattr(report, "issues", []) or []),
        )
        if not store_db:
            logger.info("--no-db: skipping persistence")
            return result
        with get_session() as session:
            repo: Any = JobRepository()
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": self._source_code},
            ).scalar()
            if source_id is None:
                raise RuntimeError(
                    f"ref.sources has no row with source_code={self._source_code!r}. "
                    "Run the seed (python -m seed.run_all) and "
                    "scripts/register_source.py --code jobmail ... before scraping."
                )
            for job in cleaned:
                try:
                    with transaction(session):
                        outcome = repo.save_cleaned_job(session, job, source_id=int(source_id))
                    if outcome == "inserted":
                        result.inserted_count += 1
                    elif outcome == "updated":
                        result.updated_count += 1
                    else:
                        result.unchanged_count += 1
                except Exception as exc:  # noqa: BLE001
                    result.failed_count += 1
                    logger.warning("failed to persist jobmail job {}: {}", job.source_job_id, exc)
            session.commit()
        logger.info(
            "jobmail run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

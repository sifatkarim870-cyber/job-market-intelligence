"""Automated ETL pipeline for Jobs.ge (Georgia). Uses a headless browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.jobsge.client import JobsGeClient
from job_market_intel.scrapers.jobsge.config import JobsGeSettings
from job_market_intel.scrapers.jobsge.parser import JobsGeParser
from job_market_intel.validation.jobsge_validator import JobsGeBatchValidator

if TYPE_CHECKING:
    from job_market_intel.cleaning.jobsge_cleaner import JobsGeCleaner
    from job_market_intel.validation.jobsge_validator import JobsGeValidationSettings


class JobsGePipelineRunResult(BaseModel):
    raw_count: int = Field(..., description="Posting pages fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    with_english_title: int = Field(
        default=0, description="Postings where the listing supplied an English title."
    )
    inserted_count: int = Field(default=0, description="New jobs inserted.")
    updated_count: int = Field(default=0, description="Existing jobs updated.")
    unchanged_count: int = Field(default=0, description="Skipped (identical content hash).")
    failed_count: int = Field(default=0, description="Records that failed persistence.")
    fetch_failures: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)


class JobsGePipeline:
    def __init__(
        self,
        settings: JobsGeSettings | None = None,
        validation_settings: JobsGeValidationSettings | None = None,
        client: JobsGeClient | None = None,
        parser: JobsGeParser | None = None,
        validator: JobsGeBatchValidator | None = None,
        cleaner: JobsGeCleaner | None = None,
        source_code: str = "jobsge",
    ) -> None:
        self._settings = settings or JobsGeSettings()
        self._validation_settings = validation_settings
        self._client = client or JobsGeClient(self._settings)
        self._parser = parser or JobsGeParser()
        self._validator = validator or JobsGeBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.jobsge_cleaner import JobsGeCleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> JobsGePipelineRunResult:
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Jobs.ge pipeline (store_db={}).", store_db)
        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the jobs.ge run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )
        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)
        result = JobsGePipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=report.passed,
            cleaned_count=len(cleaned),
            with_english_title=sum(1 for j in parsed if j.title_en),
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
                    "scripts/register_source.py --code jobsge ... before scraping."
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
                    logger.warning("failed to persist jobs.ge job {}: {}", job.source_job_id, exc)
            session.commit()
        logger.info(
            "jobs.ge run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

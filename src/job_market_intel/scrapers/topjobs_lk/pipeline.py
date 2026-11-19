"""Automated ETL pipeline for TopJobs (topjobs.lk, Sri Lanka).

Same five stages as every bespoke source in this project: fetch -> parse ->
validate -> clean -> persist. Persistence resolves the source row, writes one
``CleanedJob`` per posting through ``JobRepository`` (which owns company,
location, salary and employment-type resolution), and counts
inserted/updated/unchanged/failed per row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.topjobs_lk.client import TopJobsLkClient
from job_market_intel.scrapers.topjobs_lk.config import TopJobsLkSettings
from job_market_intel.scrapers.topjobs_lk.parser import TopJobsLkParser
from job_market_intel.validation.topjobs_lk_validator import (
    TopJobsLkBatchValidator,
)

if TYPE_CHECKING:
    from job_market_intel.cleaning.topjobs_lk_cleaner import TopJobsLkCleaner
    from job_market_intel.validation.topjobs_lk_validator import (
        TopJobsLkValidationSettings,
    )


class TopJobsLkPipelineRunResult(BaseModel):
    raw_count: int = Field(..., description="Posting records fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    with_description: int = Field(default=0, description="Ads with readable body text.")
    image_only: int = Field(default=0, description="Ads whose body is an image.")
    inserted_count: int = Field(default=0, description="New jobs inserted.")
    updated_count: int = Field(default=0, description="Existing jobs updated.")
    unchanged_count: int = Field(default=0, description="Skipped (identical content hash).")
    failed_count: int = Field(default=0, description="Records that failed persistence.")
    fetch_failures: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)


class TopJobsLkPipeline:
    def __init__(
        self,
        settings: TopJobsLkSettings | None = None,
        validation_settings: TopJobsLkValidationSettings | None = None,
        client: TopJobsLkClient | None = None,
        parser: TopJobsLkParser | None = None,
        validator: TopJobsLkBatchValidator | None = None,
        cleaner: TopJobsLkCleaner | None = None,
        source_code: str = "topjobs_lk",
    ) -> None:
        self._settings = settings or TopJobsLkSettings()
        self._validation_settings = validation_settings
        self._client = client or TopJobsLkClient(self._settings)
        self._parser = parser or TopJobsLkParser()
        self._validator = validator or TopJobsLkBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.topjobs_lk_cleaner import (
                TopJobsLkCleaner as _Cleaner,
            )

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> TopJobsLkPipelineRunResult:
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting TopJobs (Sri Lanka) pipeline (store_db={}).", store_db)
        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} listing/posting fetch failure(s) during the TopJobs run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )
        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)
        result = TopJobsLkPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=report.passed,
            cleaned_count=len(cleaned),
            with_description=sum(1 for job in parsed if job.description),
            image_only=sum(1 for job in parsed if job.description_is_image),
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
                    "scripts/register_source.py --code topjobs_lk ... before scraping."
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
                    logger.warning("failed to persist TopJobs job {}: {}", job.source_job_id, exc)
            session.commit()
        logger.info(
            "TopJobs run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

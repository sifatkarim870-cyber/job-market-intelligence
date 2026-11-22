"""Pipeline orchestrator for the National Employment Agency (Cambodia) scraper.

Fetch -> Parse -> Batch Validate -> Clean -> Persist.

The per-run cap is enforced in the client (it bounds how many detail pages are
fetched) and re-applied here before persistence. Both the ``nea_gov_kh``
source row and the ``KH`` country row are required: without the country the
``SOURCE_HOME_COUNTRY`` fallback is a silent no-op and every row lands with a
NULL country. Cambodia is seeded but holds no cities, so the fallback is what
keeps every province on Cambodia.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session

from .client import NeaGovKhClient
from .config import NeaGovKhSettings
from .models import RawNeaGovKhJob  # noqa: F401  (re-exported)
from .parser import NeaGovKhParser

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_market_intel.cleaning.nea_gov_kh_cleaner import NeaGovKhCleaner
    from job_market_intel.db.job_repository import JobRepository
    from job_market_intel.validation.nea_gov_kh_validator import NeaGovKhBatchValidator

SOURCE_CODE = "nea_gov_kh"


class NeaGovKhPipelineRunResult(BaseModel):
    """Execution summary for a single run of the NEA Cambodia pipeline."""

    raw_count: int = Field(..., description="Raw detail pages fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    fetch_failures: int = Field(0, description="Search/detail fetches that failed.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Identical content hash; skipped.")
    failed_count: int = Field(0, description="Jobs that failed persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions.session_id.")
    issues: list[str] = Field(default_factory=list, description="Validation/parse issues.")


class NeaGovKhPipeline:
    """Automated end-to-end pipeline runner for NEA Cambodia."""

    def __init__(
        self,
        settings: NeaGovKhSettings | None = None,
        validation_settings: Any | None = None,
        client: NeaGovKhClient | None = None,
        parser: NeaGovKhParser | None = None,
        validator: NeaGovKhBatchValidator | None = None,
        cleaner: NeaGovKhCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or NeaGovKhSettings()
        self.client = client or NeaGovKhClient(settings=self.settings)
        self.parser = parser or NeaGovKhParser()

        if validator is None:
            from job_market_intel.validation.nea_gov_kh_validator import (
                NeaGovKhBatchValidator,
                NeaGovKhValidationSettings,
            )

            validator = NeaGovKhBatchValidator(
                settings=validation_settings or NeaGovKhValidationSettings()
            )
        self.validator = validator

        if cleaner is None:
            from job_market_intel.cleaning.nea_gov_kh_cleaner import NeaGovKhCleaner as _Cleaner

            cleaner = _Cleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(self, *, store_db: bool = True) -> NeaGovKhPipelineRunResult:
        logger.info("Starting NEA Cambodia pipeline run (store_db={}).", store_db)

        raw_records, fetch_failures = self.client.fetch_raw_jobs()
        parsed_jobs, parse_issues = self.parser.parse_many(raw_records)

        validation_report = self.validator.validate(raw_records, parsed_jobs)
        cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)

        cap = self.settings.max_jobs_per_run
        if len(cleaned_jobs) > cap:
            logger.info(
                "NEA Cambodia run cap: keeping {} of {} cleaned jobs "
                "(NEA_GOV_KH_MAX_JOBS_PER_RUN={})",
                cap,
                len(cleaned_jobs),
                cap,
            )
            cleaned_jobs = cleaned_jobs[:cap]

        result = NeaGovKhPipelineRunResult(
            raw_count=len(raw_records),
            parsed_count=len(parsed_jobs),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            fetch_failures=len(fetch_failures),
            issues=list(parse_issues) + list(getattr(validation_report, "issues", []) or []),
        )
        if fetch_failures:
            result.issues.append(
                f"{len(fetch_failures)} search/detail fetch(es) failed; see the log for ids"
            )

        if not store_db:
            logger.info("NEA Cambodia pipeline dry-run complete (store_db=False).")
            return result

        if not cleaned_jobs:
            logger.error("NEA Cambodia cleaned zero jobs; skipping persistence.")
            return result

        self._persist(cleaned_jobs, result)
        return result

    def _persist(self, cleaned_jobs: list[Any], result: NeaGovKhPipelineRunResult) -> None:
        with get_session() as session:
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": SOURCE_CODE},
            ).scalar_one_or_none()
            if source_id is None:
                raise RuntimeError(
                    f"ref.sources has no row with source_code={SOURCE_CODE!r}. "
                    "Run scripts/register_source.py before scraping."
                )

            country_id = session.execute(
                text("SELECT country_id FROM ref.countries WHERE iso_code_2 = 'KH'")
            ).scalar_one_or_none()
            if country_id is None:
                raise RuntimeError(
                    "ref.countries has no KH row. Run the seed "
                    "(python -m seed.run_all) before scraping: without it, the "
                    "SOURCE_HOME_COUNTRY fallback is a silent no-op and every row "
                    "lands with a NULL country."
                )

            session_id = self.repository.create_scraping_session(
                session, source_id=int(source_id), trigger_type="scheduled"
            )
            result.session_id = session_id

            counts = self.repository.save_cleaned_jobs(
                session=session,
                jobs=cleaned_jobs,
                source_id=int(source_id),
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
                jobs_found=result.raw_count,
                jobs_new=counts["inserted"],
                jobs_updated=counts["updated"],
                jobs_failed=counts["failed"],
                pages_scraped=self.settings.pages_per_run,
            )

        logger.info(
            "NEA Cambodia pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )

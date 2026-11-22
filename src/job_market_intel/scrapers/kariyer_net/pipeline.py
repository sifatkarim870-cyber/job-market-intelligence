"""Pipeline orchestrator for the Kariyer.net scraper.

Fetch -> Parse -> Batch Validate -> Clean -> Persist.

The per-run cap is enforced in the client (it bounds how many detail calls are
made), and re-applied here before persistence so a run cannot write more than
intended.

The pipeline insists that both the ``kariyer_net`` source row and the ``TR``
country row exist before writing: a missing country would silently turn every
posting into a NULL-country row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session

from .client import KariyerNetClient
from .config import KariyerNetSettings
from .models import RawKariyerNetJob  # noqa: F401  (re-exported for callers)
from .parser import KariyerNetParser

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_market_intel.cleaning.kariyer_net_cleaner import KariyerNetCleaner
    from job_market_intel.db.job_repository import JobRepository
    from job_market_intel.validation.kariyer_net_validator import KariyerNetBatchValidator

SOURCE_CODE = "kariyer_net"


class KariyerNetPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Kariyer.net pipeline."""

    raw_count: int = Field(..., description="Raw records fetched (one per detail ad).")
    parsed_count: int = Field(..., description="Records that passed validation.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    fetch_failures: int = Field(0, description="Detail calls that failed.")
    inserted_count: int = Field(0, description="New jobs inserted.")
    updated_count: int = Field(0, description="Existing jobs updated.")
    unchanged_count: int = Field(0, description="Identical content hash; skipped.")
    failed_count: int = Field(0, description="Jobs that failed persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions.session_id.")
    issues: list[str] = Field(default_factory=list, description="Validation issues.")


class KariyerNetPipeline:
    """Automated end-to-end pipeline runner for Kariyer.net."""

    def __init__(
        self,
        settings: KariyerNetSettings | None = None,
        validation_settings: Any | None = None,
        client: KariyerNetClient | None = None,
        parser: KariyerNetParser | None = None,
        validator: KariyerNetBatchValidator | None = None,
        cleaner: KariyerNetCleaner | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or KariyerNetSettings()
        self.client = client or KariyerNetClient(settings=self.settings)
        self.parser = parser or KariyerNetParser()

        if validator is None:
            from job_market_intel.validation.kariyer_net_validator import (
                KariyerNetBatchValidator,
                KariyerNetValidationSettings,
            )

            validator = KariyerNetBatchValidator(
                settings=validation_settings or KariyerNetValidationSettings()
            )
        self.validator = validator

        if cleaner is None:
            from job_market_intel.cleaning.kariyer_net_cleaner import KariyerNetCleaner

            cleaner = KariyerNetCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

    def run(self, *, store_db: bool = True) -> KariyerNetPipelineRunResult:
        logger.info("Starting Kariyer.net pipeline run (store_db={}).", store_db)

        raw_records, fetch_failures = self.client.fetch_raw_jobs()
        parsed_jobs = self.parser.parse_jobs(raw_records)

        validation_report = self.validator.validate(raw_records, parsed_jobs)
        cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)

        cap = self.settings.max_jobs_per_run
        if len(cleaned_jobs) > cap:
            logger.info(
                "Kariyer.net run cap: keeping {} of {} cleaned jobs "
                "(KARIYER_NET_MAX_JOBS_PER_RUN={})",
                cap,
                len(cleaned_jobs),
                cap,
            )
            cleaned_jobs = cleaned_jobs[:cap]

        result = KariyerNetPipelineRunResult(
            raw_count=len(raw_records),
            parsed_count=len(parsed_jobs),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            fetch_failures=len(fetch_failures),
            issues=list(getattr(validation_report, "issues", []) or []),
        )
        if fetch_failures:
            result.issues.append(
                f"{len(fetch_failures)} detail call(s) failed; see the log for job ids"
            )

        if not store_db:
            logger.info("Kariyer.net pipeline dry-run complete (store_db=False).")
            return result

        if not cleaned_jobs:
            logger.error("Kariyer.net cleaned zero jobs; skipping persistence.")
            return result

        self._persist(cleaned_jobs, result)
        return result

    def _persist(self, cleaned_jobs: list[Any], result: KariyerNetPipelineRunResult) -> None:
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
                text("SELECT country_id FROM ref.countries WHERE iso_code_2 = 'TR'")
            ).scalar_one_or_none()
            if country_id is None:
                raise RuntimeError(
                    "ref.countries has no TR row. Run the seed "
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
                pages_scraped=self.settings.max_pages_per_run,
            )

        logger.info(
            "Kariyer.net pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )

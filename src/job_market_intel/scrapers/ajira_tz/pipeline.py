"""End-to-end ETL pipeline for Ajira Portal (Tanzania)."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.session import get_session
from .client import AjiraTzClient
from .config import AjiraTzSettings
from .parser import AjiraTzParser


class AjiraTzPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Ajira TZ pipeline."""

    raw_count: int = Field(..., description="Total raw postings discovered.")
    parsed_count: int = Field(..., description="Jobs successfully parsed into models.")
    validation_passed: bool = Field(default=True, description="Batch quality validation status.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(default=0, description="New jobs inserted into PostgreSQL.")
    updated_count: int = Field(default=0, description="Existing jobs updated.")
    unchanged_count: int = Field(default=0, description="Jobs skipped due to matching content hash.")
    failed_count: int = Field(default=0, description="Jobs that failed persistence.")
    session_id: int | None = Field(default=None, description="scraping_sessions.session_id.")
    issues: list[str] = Field(default_factory=list, description="Validation or pipeline issues.")


class AjiraTzPipeline:
    """Automated ETL pipeline for Ajira Portal (Tanzania)."""

    def __init__(
        self,
        settings: AjiraTzSettings | None = None,
        client: AjiraTzClient | None = None,
        parser: AjiraTzParser | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or AjiraTzSettings()
        self.client = client or AjiraTzClient(settings=self.settings)
        self.parser = parser or AjiraTzParser()
        self.repository = repository or JobRepository()

    def run(self, *, store_db: bool = True) -> AjiraTzPipelineRunResult:
        """Run the Ajira TZ pipeline end-to-end."""
        logger.info("Starting Ajira Portal (Tanzania) scraper pipeline (store_db={}).", store_db)

        raw_items = self.client.fetch_vacancy_list()
        if not raw_items:
            logger.warning("No postings returned by Ajira listing endpoint.")
            return AjiraTzPipelineRunResult(
                raw_count=0,
                parsed_count=0,
                validation_passed=False,
                cleaned_count=0,
                issues=["Zero raw items fetched from Ajira listing endpoint"],
            )

        cap = self.settings.max_jobs_per_run
        selected_raw = raw_items[:cap]
        logger.info("Selected {} items for detail retrieval (capped at {}).", len(selected_raw), cap)

        vacancy_ids = [item["id"] for item in selected_raw if "id" in item]
        details_map = self.client.fetch_all_details(vacancy_ids)

        cleaned_jobs = self.parser.parse_jobs(selected_raw, details_map)

        validation_passed = len(cleaned_jobs) > 0
        issues: list[str] = []
        if not validation_passed:
            issues.append("Zero jobs successfully parsed from Ajira feed")

        result = AjiraTzPipelineRunResult(
            raw_count=len(raw_items),
            parsed_count=len(cleaned_jobs),
            validation_passed=validation_passed,
            cleaned_count=len(cleaned_jobs),
            issues=issues,
        )

        if not store_db:
            logger.info("Dry-run mode active; skipping database persistence.")
            return result

        with get_session() as session:
            # Ensure country Tanzania exists in ref.countries
            session.execute(
                text(
                    """
                    INSERT INTO ref.countries (iso_code_2, iso_code_3, country_name, continent, default_currency_id)
                    VALUES ('TZ', 'TZA', 'Tanzania', 'Africa', 503)
                    ON CONFLICT (iso_code_2) DO UPDATE SET country_name = EXCLUDED.country_name
                    """
                )
            )

            # Ensure source exists in ref.sources
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = 'ajira_tz'")
            ).scalar_one_or_none()
            if source_id is None:
                source_id = session.execute(
                    text(
                        """
                        INSERT INTO ref.sources (source_code, source_name, source_type, is_active)
                        VALUES ('ajira_tz', 'Ajira Portal (Tanzania)', 'job_board', true)
                        RETURNING source_id
                        """
                    )
                ).scalar_one()

            session.commit()

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

            status = "completed" if counts["failed"] == 0 and len(cleaned_jobs) > 0 else "partial"
            self.repository.finish_scraping_session(
                session=session,
                session_id=session_id,
                status=status,
                jobs_found=len(raw_items),
                jobs_new=counts["inserted"],
                jobs_updated=counts["updated"],
                jobs_failed=counts["failed"],
                pages_scraped=1,
            )
            session.commit()

        logger.info(
            "Ajira Portal (Tanzania) scrape complete: {} inserted, {} updated, {} unchanged, {} failed.",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

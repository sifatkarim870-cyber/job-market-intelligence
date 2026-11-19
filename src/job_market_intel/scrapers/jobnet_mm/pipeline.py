"""Pipeline orchestrator for the JobNet (Myanmar) scraper."""

from __future__ import annotations

from sqlalchemy import text

from loguru import logger
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.session import get_session
from job_market_intel.scrapers.jobnet_mm.client import JobnetClient
from job_market_intel.scrapers.jobnet_mm.config import JobnetSettings
from job_market_intel.scrapers.jobnet_mm.models import JobnetPipelineRunResult
from job_market_intel.scrapers.jobnet_mm.parser import JobnetParser


class JobnetPipeline:
    """Orchestrates discover -> fetch -> parse -> validate -> persist for JobNet Myanmar."""

    def __init__(
        self,
        settings: JobnetSettings | None = None,
        client: JobnetClient | None = None,
        parser: JobnetParser | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or JobnetSettings()
        self.client = client or JobnetClient(settings=self.settings)
        self.parser = parser or JobnetParser()
        self.repository = repository or JobRepository()

    def run(self, *, store_db: bool = True) -> JobnetPipelineRunResult:
        """Run the JobNet Myanmar pipeline end-to-end."""
        logger.info("Starting JobNet (Myanmar) scraper pipeline (store_db={}).", store_db)

        targets = self.client.fetch_job_urls(max_jobs=self.settings.max_jobs_per_run)
        if not targets:
            logger.warning("No job items discovered from JobNet search directory.")
            return JobnetPipelineRunResult(
                raw_count=0,
                parsed_count=0,
                validation_passed=False,
                cleaned_count=0,
                issues=["Zero job items discovered from JobNet search directory"],
            )

        cap = self.settings.max_jobs_per_run
        selected_targets = targets[:cap]
        logger.info("Selected {} items for detail retrieval (capped at {}).", len(selected_targets), cap)

        raw_jobs = self.client.fetch_all_details(selected_targets)
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        validation_passed = len(parsed_jobs) > 0
        issues: list[str] = []
        if not validation_passed:
            issues.append("Zero jobs successfully parsed from JobNet detail pages")

        result = JobnetPipelineRunResult(
            raw_count=len(targets),
            parsed_count=len(parsed_jobs),
            validation_passed=validation_passed,
            cleaned_count=len(parsed_jobs),
            issues=issues,
        )

        if not store_db:
            logger.info("Dry-run mode active; skipping database persistence.")
            return result

        if not validation_passed:
            logger.error("Validation failed; skipping persistence to avoid bad data.")
            return result

        with get_session() as session:
            # Ensure country Myanmar exists in ref.countries
            session.execute(
                text(
                    """
                    INSERT INTO ref.countries (iso_code_2, iso_code_3, country_name, continent, default_currency_id)
                    VALUES ('MM', 'MMR', 'Myanmar', 'Asia', 3409)
                    ON CONFLICT (iso_code_2) DO UPDATE SET country_name = EXCLUDED.country_name
                    """
                )
            )

            # Ensure source exists in ref.sources
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = 'jobnet_mm'")
            ).scalar_one_or_none()
            if source_id is None:
                source_id = session.execute(
                    text(
                        """
                        INSERT INTO ref.sources (source_code, source_name, source_type, is_active)
                        VALUES ('jobnet_mm', 'JobNet Myanmar', 'job_board', true)
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
                jobs=parsed_jobs,
                source_id=source_id,
                session_id=session_id,
            )

            result.inserted_count = counts["inserted"]
            result.updated_count = counts["updated"]
            result.unchanged_count = counts["unchanged"]
            result.failed_count = counts["failed"]

            status = "completed" if counts["failed"] == 0 and len(parsed_jobs) > 0 else "partial"
            self.repository.finish_scraping_session(
                session=session,
                session_id=session_id,
                status=status,
                jobs_found=len(targets),
                jobs_new=counts["inserted"],
                jobs_updated=counts["updated"],
                jobs_failed=counts["failed"],
                pages_scraped=self.settings.max_pages,
            )

        logger.info(
            "JobNet Myanmar pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

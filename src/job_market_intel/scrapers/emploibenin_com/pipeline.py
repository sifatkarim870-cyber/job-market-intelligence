"""Pipeline orchestrator for the Emploi Bénin (emploibenin.com) scraper.

Same five stages as every bespoke source: discover -> fetch -> parse ->
validate -> persist. The board is a single-country AfricaWork portal, so the
pipeline insists that both the ``emploibenin_com`` source row and the ``BJ``
country row exist before writing: a missing country would silently turn every
posting into a NULL-country row, which is the exact defect the Sri Lanka work
fixed and the DR Congo work repeated.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.session import get_session

from .client import EmploiBeninClient
from .config import EmploiBeninSettings
from .models import EmploiBeninPipelineRunResult
from .parser import EmploiBeninParser

SOURCE_CODE = "emploibenin_com"


class EmploiBeninPipeline:
    """Orchestrates discover -> fetch -> parse -> validate -> persist."""

    def __init__(
        self,
        settings: EmploiBeninSettings | None = None,
        client: EmploiBeninClient | None = None,
        parser: EmploiBeninParser | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or EmploiBeninSettings()
        self.client = client or EmploiBeninClient(settings=self.settings)
        self.parser = parser or EmploiBeninParser()
        self.repository = repository or JobRepository()

    def run(self, *, store_db: bool = True) -> EmploiBeninPipelineRunResult:
        """Run the Emploi Bénin pipeline end-to-end."""
        logger.info("Starting Emploi Bénin (Benin) scraper pipeline (store_db={}).", store_db)

        targets, pages_scraped = self.client.fetch_job_urls(max_jobs=self.settings.max_jobs_per_run)
        result = EmploiBeninPipelineRunResult(
            raw_count=len(targets),
            pages_scraped=pages_scraped,
        )
        if not targets:
            logger.warning("No job items discovered from the Emploi Bénin search directory.")
            result.issues.append("Zero job items discovered from Emploi Bénin search directory")
            return result

        raw_jobs = self.client.fetch_all_details(targets)
        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        result.parsed_count = len(parsed_jobs)
        result.cleaned_count = len(parsed_jobs)
        result.validation_passed = len(parsed_jobs) > 0
        if not result.validation_passed:
            result.issues.append("Zero jobs successfully parsed from Emploi Bénin detail pages")

        if not store_db:
            logger.info("Dry-run mode active; skipping database persistence.")
            return result
        if not result.validation_passed:
            logger.error("Validation failed; skipping persistence to avoid bad data.")
            return result

        with get_session() as session:
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": SOURCE_CODE},
            ).scalar_one_or_none()
            if source_id is None:
                raise RuntimeError(
                    f"ref.sources has no row with source_code={SOURCE_CODE!r}. "
                    "Run the seed and scripts/register_source.py before scraping."
                )

            country_id = session.execute(
                text("SELECT country_id FROM ref.countries WHERE iso_code_2 = 'BJ'")
            ).scalar_one_or_none()
            if country_id is None:
                raise RuntimeError(
                    "ref.countries has no BJ row. Run the seed (python -m seed.run_all) "
                    "before scraping: without it, the SOURCE_HOME_COUNTRY fallback is a "
                    "silent no-op and every row lands with a NULL country."
                )

            session_id = self.repository.create_scraping_session(
                session, source_id=int(source_id), trigger_type="scheduled"
            )
            result.session_id = session_id

            counts = self.repository.save_cleaned_jobs(
                session=session,
                jobs=parsed_jobs,
                source_id=int(source_id),
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
                pages_scraped=pages_scraped,
            )

        logger.info(
            "Emploi Bénin pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

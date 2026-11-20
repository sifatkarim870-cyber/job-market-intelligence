"""Pipeline orchestrator for the Empléate (Spain) scraper.

Same five stages as every bespoke source: discover -> fetch -> parse ->
validate -> persist. Discovery and fetch collapse into one Solr query per
100 postings, so there is no separate detail stage.

The pipeline insists that both the ``empleate_es`` source row and the
``ES`` country row exist before writing: a missing country would silently
turn every posting into a NULL-country row, which is the exact defect the
Sri Lanka work fixed.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.session import get_session

from .client import EmpleateEsClient
from .config import EmpleateEsSettings
from .models import EmpleateEsPipelineRunResult
from .parser import EmpleateEsParser

SOURCE_CODE = "empleate_es"


class EmpleateEsPipeline:
    """Orchestrates discover -> fetch -> parse -> validate -> persist for Empléate."""

    def __init__(
        self,
        settings: EmpleateEsSettings | None = None,
        client: EmpleateEsClient | None = None,
        parser: EmpleateEsParser | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or EmpleateEsSettings()
        self.client = client or EmpleateEsClient(settings=self.settings)
        self.parser = parser or EmpleateEsParser()
        self.repository = repository or JobRepository()

    def run(self, *, store_db: bool = True) -> EmpleateEsPipelineRunResult:
        """Run the Empléate pipeline end-to-end."""
        logger.info("Starting Empléate (Spain) scraper pipeline (store_db={}).", store_db)

        raw_jobs, pages_scraped, total_available = self.client.fetch_jobs(
            max_jobs=self.settings.max_jobs_per_run
        )
        result = EmpleateEsPipelineRunResult(
            raw_count=len(raw_jobs),
            pages_scraped=pages_scraped,
            total_available=total_available,
        )
        if not raw_jobs:
            logger.warning("No postings returned by the Empléate search API.")
            result.issues.append("Zero postings returned by the Empléate search API")
            return result

        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        result.parsed_count = len(parsed_jobs)
        result.cleaned_count = len(parsed_jobs)
        result.validation_passed = len(parsed_jobs) > 0
        if not result.validation_passed:
            result.issues.append("Zero jobs successfully parsed from Empléate documents")

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
                text("SELECT country_id FROM ref.countries WHERE iso_code_2 = 'ES'")
            ).scalar_one_or_none()
            if country_id is None:
                raise RuntimeError(
                    "ref.countries has no ES row. Run the seed (python -m seed.run_all) "
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
                jobs_found=len(raw_jobs),
                jobs_new=counts["inserted"],
                jobs_updated=counts["updated"],
                jobs_failed=counts["failed"],
                pages_scraped=pages_scraped,
            )

        logger.info(
            "Empléate pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

"""Pipeline orchestrator for the Jobindex (jobindex.dk) scraper.

Same five stages as every bespoke source: discover -> fetch -> parse ->
validate -> persist. Discovery is the sitemap-seeded area-page walk and fetch
is one or two requests per ad, so there is no separate listing stage.

The pipeline insists that both the ``jobindex_dk`` source row and the ``DK``
country row exist before writing: a missing country would silently turn every
posting into a NULL-country row, which is the exact defect the Sri Lanka work
fixed.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.session import get_session

from .client import JobIndexClient
from .config import JobIndexSettings
from .models import JobIndexPipelineRunResult
from .parser import JobIndexParser

SOURCE_CODE = "jobindex_dk"


class JobIndexPipeline:
    """Orchestrates discover -> fetch -> parse -> validate -> persist."""

    def __init__(
        self,
        settings: JobIndexSettings | None = None,
        client: JobIndexClient | None = None,
        parser: JobIndexParser | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or JobIndexSettings()
        self.client = client or JobIndexClient(settings=self.settings)
        self.parser = parser or JobIndexParser()
        self.repository = repository or JobRepository()

    def run(self, *, store_db: bool = True) -> JobIndexPipelineRunResult:
        """Run the jobindex.dk pipeline end-to-end."""
        logger.info("Starting Jobindex (Denmark) scraper pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures, pages_scraped, discovered = self.client.fetch_raw_jobs(
            max_jobs=self.settings.max_jobs_per_run
        )
        result = JobIndexPipelineRunResult(
            raw_count=len(raw_jobs),
            pages_scraped=pages_scraped,
            discovered_count=discovered,
            fetch_failures=len(fetch_failures),
        )
        if fetch_failures:
            result.issues.append(
                f"{len(fetch_failures)} ad page(s) failed to fetch; see the log for ids"
            )
        if not raw_jobs:
            logger.warning("No Jobindex ad pages were fetched.")
            result.issues.append("Zero ad pages fetched from jobindex.dk")
            return result

        parsed_jobs = self.parser.parse_jobs(raw_jobs)

        result.parsed_count = len(parsed_jobs)
        result.cleaned_count = len(parsed_jobs)
        result.validation_passed = len(parsed_jobs) > 0
        if not result.validation_passed:
            result.issues.append("Zero jobs successfully parsed from jobindex.dk pages")

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
                text("SELECT country_id FROM ref.countries WHERE iso_code_2 = 'DK'")
            ).scalar_one_or_none()
            if country_id is None:
                raise RuntimeError(
                    "ref.countries has no DK row. Run the seed (python -m seed.run_all) "
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
            "Jobindex pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

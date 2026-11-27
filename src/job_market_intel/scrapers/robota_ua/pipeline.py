"""Pipeline orchestrator for the Robota.ua (robota.ua, Ukraine) scraper.

Same stages as every bespoke source: discover -> parse -> validate -> persist.
The GraphQL query already returns full detail, so "fetch" and "discover" are
one stage. The pipeline insists that both the ``robota_ua`` source row and the
``UA`` country row exist before writing: without the country the
``SOURCE_HOME_COUNTRY`` fallback is a silent no-op and every remote row lands
with a NULL country.

When storing, the run first loads the source's already-stored
``source_job_ids`` and passes them to the client as an exclusion, so a capped
window fetches only *unseen* ads from the 97k+ board instead of re-reading the
same newest page forever. If that lookup fails the run proceeds without the
exclusion rather than skipping the scrape.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import text

from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.session import get_session

from .client import RobotaUaClient
from .config import RobotaUaSettings
from .models import RobotaUaPipelineRunResult
from .parser import RobotaUaParser

SOURCE_CODE = "robota_ua"
HOME_COUNTRY_ISO2 = "UA"


class RobotaUaPipeline:
    """Orchestrates discover -> parse -> validate -> persist."""

    def __init__(
        self,
        settings: RobotaUaSettings | None = None,
        client: RobotaUaClient | None = None,
        parser: RobotaUaParser | None = None,
        repository: JobRepository | None = None,
    ) -> None:
        self.settings = settings or RobotaUaSettings()
        self.client = client or RobotaUaClient(settings=self.settings)
        self.parser = parser or RobotaUaParser()
        self.repository = repository or JobRepository()

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> RobotaUaPipelineRunResult:
        """Run the Robota.ua pipeline end-to-end."""
        logger.info("Starting Robota.ua (Ukraine) scraper pipeline (store_db={}).", store_db)

        exclude_ids = self._load_known_ids(session_override) if store_db else None
        raw_jobs, pages_scraped = self.client.fetch_raw_jobs(exclude_ids=exclude_ids)

        result = RobotaUaPipelineRunResult(
            raw_count=len(raw_jobs),
            pages_scraped=pages_scraped,
        )

        if not raw_jobs:
            logger.info(
                "No unseen Robota.ua postings this run ({} known excluded); "
                "corpus covered, nothing to persist.",
                len(exclude_ids or ()),
            )
            result.validation_passed = True
            return result

        cleaned_jobs = self.parser.parse_jobs(raw_jobs)
        result.parsed_count = len(cleaned_jobs)
        result.cleaned_count = len(cleaned_jobs)
        result.validation_passed = len(cleaned_jobs) > 0
        if not result.validation_passed:
            result.issues.append("Zero jobs successfully parsed from Robota.ua GraphQL items")

        if not store_db:
            logger.info("Dry-run mode active; skipping database persistence.")
            return result
        if not result.validation_passed:
            logger.error("Validation failed; skipping persistence to avoid bad data.")
            return result

        if session_override is not None:
            self._persist_with_session(session_override, cleaned_jobs, len(raw_jobs), result)
        else:
            with get_session() as session:
                self._persist_with_session(session, cleaned_jobs, len(raw_jobs), result)

        logger.info(
            "Robota.ua pipeline complete: inserted={}, updated={}, unchanged={}, failed={}",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

    def _load_known_ids(self, session_override: Any | None) -> set[str] | None:
        """Already-stored robota_ua ids for skip-known selection.

        Returns ``None`` (plain head-of-board window) when the lookup cannot
        run, so a database outage degrades to the plain fetch rather than
        turning into "no scrape at all".
        """
        try:
            if session_override is not None:
                return self._known_ids_in(session_override)
            with get_session() as session:
                return self._known_ids_in(session)
        except Exception as exc:  # noqa: BLE001 - degradation, not silence
            logger.warning(
                "Could not load known Robota.ua source_job_ids; proceeding "
                "without skip-known exclusion: {}",
                exc,
            )
            return None

    def _known_ids_in(self, session: Any) -> set[str]:
        source_id = self.repository.get_source_id_by_code(session, SOURCE_CODE)
        return self.repository.get_all_source_job_ids(session, source_id)

    def _persist_with_session(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        raw_count: int,
        result: RobotaUaPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, SOURCE_CODE)

        country_id = session.execute(
            text("SELECT country_id FROM ref.countries WHERE iso_code_2 = :iso"),
            {"iso": HOME_COUNTRY_ISO2},
        ).scalar_one_or_none()
        if country_id is None:
            raise RuntimeError(
                "ref.countries has no UA row. Run the seed (python -m seed.run_all) "
                "before scraping: without it, the SOURCE_HOME_COUNTRY fallback is a "
                "silent no-op and every row lands with a NULL country."
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

        status = "completed" if counts["failed"] == 0 and len(cleaned_jobs) > 0 else "partial"
        self.repository.finish_scraping_session(
            session=session,
            session_id=session_id,
            status=status,
            jobs_found=raw_count,
            jobs_new=counts["inserted"],
            jobs_updated=counts["updated"],
            jobs_failed=counts["failed"],
            pages_scraped=result.pages_scraped,
        )

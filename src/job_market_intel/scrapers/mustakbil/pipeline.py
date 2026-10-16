"""scrapers.mustakbil.pipeline
=============================

Automated ETL pipeline for Mustakbil: Fetching -> Parsing -> Batch Validation
-> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.apna/pipeline.py`` establishes, including the
per-row savepoint: the JSON-LD salary ``unitText`` has to be translated into the
corpus's five-value pay-period vocabulary, and one mistranslation violates
``ck_job_salaries_pay_period``, which aborts the enclosing transaction and takes
every later row with it.

The Mustakbil-specific concern is that the site **rate-limits at the connection
level** rather than returning 429. A burst of listing fetches succeeds and then
every detail fetch fails, each caught by the per-row savepoint, so a too-aggressive
delay produces a run that reports success while persisting nothing. The long
default delay in :mod:`.config` is the mitigation, and a run that reports a high
``fetch_failures`` count is the symptom to look for.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.mustakbil.client import MustakbilClient
from job_market_intel.scrapers.mustakbil.config import MustakbilSettings
from job_market_intel.scrapers.mustakbil.parser import MustakbilParser
from job_market_intel.validation.mustakbil_validator import (
    MustakbilBatchValidator,
    MustakbilValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
MustakbilCleaner = None


class MustakbilPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Mustakbil pipeline."""

    raw_count: int = Field(..., description="Posting pages fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    inserted_count: int = Field(default=0, description="New jobs inserted.")
    updated_count: int = Field(default=0, description="Existing jobs updated.")
    unchanged_count: int = Field(default=0, description="Skipped (identical content hash).")
    failed_count: int = Field(default=0, description="Records that failed persistence.")
    fetch_failures: int = Field(
        default=0, description="Postings or listings that failed during fetch."
    )
    session_id: int | None = Field(default=None, description="ops.scraping_sessions id.")
    issues: list[str] = Field(default_factory=list)


class MustakbilPipeline:
    """Automated end-to-end pipeline runner for Mustakbil."""

    def __init__(
        self,
        settings: MustakbilSettings | None = None,
        validation_settings: MustakbilValidationSettings | None = None,
        client: MustakbilClient | None = None,
        parser: MustakbilParser | None = None,
        validator: MustakbilBatchValidator | None = None,
        cleaner: MustakbilCleaner | None = None,
        source_code: str = "mustakbil",
    ) -> None:
        self._settings = settings or MustakbilSettings()
        self._validation_settings = validation_settings
        self._client = client or MustakbilClient(self._settings)
        self._parser = parser or MustakbilParser()
        self._validator = validator or MustakbilBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.mustakbil_cleaner import (
                MustakbilCleaner as _Cleaner,
            )

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> MustakbilPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Mustakbil pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the Mustakbil run: {} "
                "-- a high count here usually means the inter-request delay is "
                "too low for this site, which throttles at the connection level.",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = MustakbilPipelineRunResult(
            raw_count=len(raw_jobs),
            parsed_count=len(parsed),
            validation_passed=report.passed,
            cleaned_count=len(cleaned),
            fetch_failures=len(fetch_failures),
            issues=list(parse_issues) + list(getattr(report, "issues", []) or []),
        )

        if not store_db:
            logger.info("--no-db: skipping persistence")
            return result

        with get_session() as session:
            repo: Any = JobRepository()
            # Resolved by source_code, never hardcoded: source_id is a
            # per-database sequence value.
            source_id = session.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": self._source_code},
            ).scalar()
            if source_id is None:
                raise RuntimeError(
                    f"ref.sources has no row with source_code={self._source_code!r}. "
                    "Run the seed (python -m seed.run_all) and "
                    "scripts/register_source.py --code mustakbil ... before scraping."
                )
            for job in cleaned:
                # Per-row savepoint: see ck_job_salaries_pay_period above.
                try:
                    with transaction(session):
                        outcome = repo.save_cleaned_job(session, job, source_id=int(source_id))
                    if outcome == "inserted":
                        result.inserted_count += 1
                    elif outcome == "updated":
                        result.updated_count += 1
                    else:
                        result.unchanged_count += 1
                except Exception as exc:  # noqa: BLE001 - one row must not stop the batch
                    result.failed_count += 1
                    logger.warning("failed to persist Mustakbil job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "Mustakbil run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

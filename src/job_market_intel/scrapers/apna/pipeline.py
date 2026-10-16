"""scrapers.apna.pipeline
=======================

Automated ETL pipeline for Apna: Fetching -> Parsing -> Batch Validation
-> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.careers24/pipeline.py`` establishes, including the
per-row savepoint: the JSON-LD salary ``unitText`` has to be translated into the
corpus's five-value pay-period vocabulary, and one mistranslation violates
``ck_job_salaries_pay_period``, which aborts the enclosing transaction and takes
every later row with it.

The Apna-specific concern is that every measured salary is **monthly**. The
period is therefore ``monthly``, not the ``yearly`` default the other cleaners
use, and getting it wrong would overstate every figure in the source by twelve
times rather than raising an error -- which is the worse kind of bug.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.apna.client import ApnaClient
from job_market_intel.scrapers.apna.config import ApnaSettings
from job_market_intel.scrapers.apna.parser import ApnaParser
from job_market_intel.validation.apna_validator import (
    ApnaBatchValidator,
    ApnaValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
ApnaCleaner = None


class ApnaPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Apna pipeline."""

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


class ApnaPipeline:
    """Automated end-to-end pipeline runner for Apna."""

    def __init__(
        self,
        settings: ApnaSettings | None = None,
        validation_settings: ApnaValidationSettings | None = None,
        client: ApnaClient | None = None,
        parser: ApnaParser | None = None,
        validator: ApnaBatchValidator | None = None,
        cleaner: ApnaCleaner | None = None,
        source_code: str = "apna",
    ) -> None:
        self._settings = settings or ApnaSettings()
        self._validation_settings = validation_settings
        self._client = client or ApnaClient(self._settings)
        self._parser = parser or ApnaParser()
        self._validator = validator or ApnaBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.apna_cleaner import ApnaCleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> ApnaPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Apna pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the Apna run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = ApnaPipelineRunResult(
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
                    "scripts/register_source.py --code apna ... before scraping."
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
                    logger.warning("failed to persist Apna job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "Apna run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

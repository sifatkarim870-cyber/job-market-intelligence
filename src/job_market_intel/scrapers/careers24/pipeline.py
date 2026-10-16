"""scrapers.careers24.pipeline
=============================

Automated ETL pipeline for Careers24: Fetching -> Parsing -> Batch Validation
-> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.builtin/pipeline.py`` establishes, including the
per-row savepoint: the JSON-LD salary ``unitText`` has to be translated into the
corpus's five-value pay-period vocabulary, and one mistranslation violates
``ck_job_salaries_pay_period``, which aborts the enclosing transaction and takes
every later row with it.

The Careers24-specific concern is that ``baseSalary`` is absent on 6 of 8
postings measured and that, when present, it is a single figure rather than a
band. Neither is treated as required -- but the observed shape is recorded in
``raw_payload`` so that a change in the site's markup shows up as a drop in
salary coverage rather than passing silently.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.careers24.client import Careers24Client
from job_market_intel.scrapers.careers24.config import Careers24Settings
from job_market_intel.scrapers.careers24.parser import Careers24Parser
from job_market_intel.validation.careers24_validator import (
    Careers24BatchValidator,
    Careers24ValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
Careers24Cleaner = None


class Careers24PipelineRunResult(BaseModel):
    """Execution summary for a single run of the Careers24 pipeline."""

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


class Careers24Pipeline:
    """Automated end-to-end pipeline runner for Careers24."""

    def __init__(
        self,
        settings: Careers24Settings | None = None,
        validation_settings: Careers24ValidationSettings | None = None,
        client: Careers24Client | None = None,
        parser: Careers24Parser | None = None,
        validator: Careers24BatchValidator | None = None,
        cleaner: Careers24Cleaner | None = None,
        source_code: str = "careers24",
    ) -> None:
        self._settings = settings or Careers24Settings()
        self._validation_settings = validation_settings
        self._client = client or Careers24Client(self._settings)
        self._parser = parser or Careers24Parser()
        self._validator = validator or Careers24BatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.careers24_cleaner import Careers24Cleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> Careers24PipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Careers24 pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the Careers24 run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = Careers24PipelineRunResult(
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
                    "scripts/register_source.py careers24 before scraping."
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
                    logger.warning("failed to persist Careers24 job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "Careers24 run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

"""scrapers.angola_emprego.pipeline
==================================

Automated ETL pipeline for Angola Emprego: Fetching -> Parsing -> Batch
Validation -> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.vagas_com_br/pipeline.py`` establishes, including
the per-row savepoint. Angola Emprego needs that less than most sources: it
publishes no ``baseSalary`` on any measured posting, so nothing can reach
``ck_job_salaries_pay_period``. The savepoint is kept anyway because the
constraint is a property of the schema, not of a source.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.angola_emprego.client import AngolaEmpregoClient
from job_market_intel.scrapers.angola_emprego.config import AngolaEmpregoSettings
from job_market_intel.scrapers.angola_emprego.parser import AngolaEmpregoParser
from job_market_intel.validation.angola_emprego_validator import (
    AngolaEmpregoBatchValidator,
    AngolaEmpregoValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
AngolaEmpregoCleaner = None


class AngolaEmpregoPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Angola Emprego pipeline."""

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


class AngolaEmpregoPipeline:
    """Automated end-to-end pipeline runner for Angola Emprego."""

    def __init__(
        self,
        settings: AngolaEmpregoSettings | None = None,
        validation_settings: AngolaEmpregoValidationSettings | None = None,
        client: AngolaEmpregoClient | None = None,
        parser: AngolaEmpregoParser | None = None,
        validator: AngolaEmpregoBatchValidator | None = None,
        cleaner: AngolaEmpregoCleaner | None = None,
        source_code: str = "angola_emprego",
    ) -> None:
        self._settings = settings or AngolaEmpregoSettings()
        self._validation_settings = validation_settings
        self._client = client or AngolaEmpregoClient(self._settings)
        self._parser = parser or AngolaEmpregoParser()
        self._validator = validator or AngolaEmpregoBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.angola_emprego_cleaner import (
                AngolaEmpregoCleaner as _Cleaner,
            )

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> AngolaEmpregoPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Angola Emprego pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the Angola Emprego run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = AngolaEmpregoPipelineRunResult(
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
                    "scripts/register_source.py --code angola_emprego ... before scraping."
                )
            for job in cleaned:
                # Per-row savepoint: the salary pay-period constraint is a
                # property of the schema, so it applies to every source.
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
                    logger.warning(
                        "failed to persist Angola Emprego job {}: {}", job.source_job_id, exc
                    )
            session.commit()

        logger.info(
            "Angola Emprego run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

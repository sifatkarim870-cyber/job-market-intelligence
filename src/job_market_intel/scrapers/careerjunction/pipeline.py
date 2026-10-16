"""scrapers.careerjunction.pipeline
=================================

Automated ETL pipeline for CareerJunction: Fetching -> Parsing -> Batch
Validation -> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.net_empregos/pipeline.py`` establishes, including
the per-row savepoint. CareerJunction needs that less than most sources: it
publishes no ``baseSalary`` on any measured posting, so there is no ``unitText``
to translate and nothing that can reach ``ck_job_salaries_pay_period``. The
savepoint is kept anyway because the constraint is a property of the schema, not
of a source.

The CareerJunction-specific concern is the malformed JSON-LD. The description
string contains raw newlines and HTML entities, which makes ``json.loads``
raise ``Invalid control character``. The parser uses ``json.loads(block,
strict=False)``, which tolerates control characters inside strings.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.careerjunction.client import CareerJunctionClient
from job_market_intel.scrapers.careerjunction.config import CareerJunctionSettings
from job_market_intel.scrapers.careerjunction.parser import CareerJunctionParser
from job_market_intel.validation.careerjunction_validator import (
    CareerJunctionBatchValidator,
    CareerJunctionValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
CareerJunctionCleaner = None


class CareerJunctionPipelineRunResult(BaseModel):
    """Execution summary for a single run of the CareerJunction pipeline."""

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


class CareerJunctionPipeline:
    """Automated end-to-end pipeline runner for CareerJunction."""

    def __init__(
        self,
        settings: CareerJunctionSettings | None = None,
        validation_settings: CareerJunctionValidationSettings | None = None,
        client: CareerJunctionClient | None = None,
        parser: CareerJunctionParser | None = None,
        validator: CareerJunctionBatchValidator | None = None,
        cleaner: CareerJunctionCleaner | None = None,
        source_code: str = "careerjunction",
    ) -> None:
        self._settings = settings or CareerJunctionSettings()
        self._validation_settings = validation_settings
        self._client = client or CareerJunctionClient(self._settings)
        self._parser = parser or CareerJunctionParser()
        self._validator = validator or CareerJunctionBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.careerjunction_cleaner import (
                CareerJunctionCleaner as _Cleaner,
            )

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def run(self, *, store_db: bool = True) -> CareerJunctionPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting CareerJunction pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/listing fetch failure(s) during the CareerJunction run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        report = self._validator.validate(raw_jobs, parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = CareerJunctionPipelineRunResult(
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
                    "scripts/register_source.py --code careerjunction ... before scraping."
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
                        "failed to persist CareerJunction job {}: {}", job.source_job_id, exc
                    )
            session.commit()

        logger.info(
            "CareerJunction run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

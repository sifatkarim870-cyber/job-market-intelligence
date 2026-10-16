"""scrapers.alfred.pipeline
==========================

Automated ETL pipeline for Alfred: Fetching -> Parsing -> Batch Validation
-> Text Cleaning -> Database Storage & Deduplication.

Follows the shape ``scrapers.mustakbil/pipeline.py`` establishes, including the
per-row savepoint. Alfred needs that less than most sources: it publishes no
``baseSalary`` on any measured posting, so there is no ``unitText`` to translate
and nothing that can reach ``ck_job_salaries_pay_period``. The savepoint is kept
anyway because the constraint is a property of the schema, not of a source.

The Alfred-specific concern is the general-application pages. A handful of
sitemap entries are not vacancies at all: they carry a description of the
employer's business rather than of a role, and one measured example runs to
591 characters of marketing copy. They are dropped in the pipeline and counted
in the run result, so the exclusion is visible in the summary rather than
silently shrinking the batch.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.scrapers.alfred.client import AlfredClient
from job_market_intel.scrapers.alfred.config import AlfredSettings
from job_market_intel.scrapers.alfred.models import RawAlfredJob
from job_market_intel.scrapers.alfred.parser import AlfredParser, is_general_application
from job_market_intel.validation.alfred_validator import (
    AlfredBatchValidator,
    AlfredValidationSettings,
)

# Imported lazily inside __init__: the cleaner imports this package's models via
# __init__, which imports this module -- a top-level import here is circular.
AlfredCleaner = None


class AlfredPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Alfred pipeline."""

    raw_count: int = Field(..., description="Posting pages fetched.")
    parsed_count: int = Field(..., description="Records parsed into typed models.")
    validation_passed: bool = Field(..., description="Whether batch validation passed.")
    cleaned_count: int = Field(..., description="Records cleaned and normalized.")
    inserted_count: int = Field(default=0, description="New jobs inserted.")
    updated_count: int = Field(default=0, description="Existing jobs updated.")
    unchanged_count: int = Field(default=0, description="Skipped (identical content hash).")
    failed_count: int = Field(default=0, description="Records that failed persistence.")
    fetch_failures: int = Field(
        default=0, description="Postings or sitemaps that failed during fetch."
    )
    general_application_dropped: int = Field(
        default=0, description="Sitemap entries that were not vacancies."
    )
    session_id: int | None = Field(default=None, description="ops.scraping_sessions id.")
    issues: list[str] = Field(default_factory=list)


class AlfredPipeline:
    """Automated end-to-end pipeline runner for Alfred."""

    def __init__(
        self,
        settings: AlfredSettings | None = None,
        validation_settings: AlfredValidationSettings | None = None,
        client: AlfredClient | None = None,
        parser: AlfredParser | None = None,
        validator: AlfredBatchValidator | None = None,
        cleaner: AlfredCleaner | None = None,
        source_code: str = "alfred",
    ) -> None:
        self._settings = settings or AlfredSettings()
        self._validation_settings = validation_settings
        self._client = client or AlfredClient(self._settings)
        self._parser = parser or AlfredParser()
        self._validator = validator or AlfredBatchValidator(validation_settings)
        if cleaner is not None:
            self._cleaner = cleaner
        else:
            from job_market_intel.cleaning.alfred_cleaner import AlfredCleaner as _Cleaner

            self._cleaner = _Cleaner()
        self._source_code = source_code

    def _drop_general_application(self, jobs: list[RawAlfredJob]) -> tuple[list[RawAlfredJob], int]:
        """Remove general-application pages from the parsed batch.

        Measured on the first live run: **19 of 28** stored rows were
        general-application pages, not vacancies. The first implementation
        matched a single exact slug and caught 2 of them, while the run summary
        cheerfully reported "2 dropped" -- which made a 68% contamination rate
        look like a rounding error.

        It matches on the **title** instead, after parsing, because the slug is
        not a safe discriminator: three real vacancies from three employers
        ("Fullt starf hjá Brikk", "Vilt þú taka þátt...", "Við leitum að
        reglulega að verkafólki") reuse the same ``almenn-umsokn-`` prefix. A
        slug filter would have discarded those three genuine jobs.

        Dropped before validation, so the health report describes the postings
        that were actually candidates for storage.
        """
        if not self._settings.drop_general_application_pages:
            return jobs, 0
        kept: list[RawAlfredJob] = []
        dropped = 0
        for job in jobs:
            if is_general_application(job.title):
                dropped += 1
                continue
            kept.append(job)
        if dropped:
            logger.info(
                "alfred: dropped {} general-application page(s) that are not vacancies",
                dropped,
            )
        return kept, dropped

    def run(self, *, store_db: bool = True) -> AlfredPipelineRunResult:
        """Fetch, parse, validate, clean and (optionally) persist one batch."""
        from job_market_intel.db.job_repository import JobRepository

        logger.info("Starting Alfred pipeline (store_db={}).", store_db)

        raw_jobs, fetch_failures = self._client.fetch_raw_jobs()
        if fetch_failures:
            logger.warning(
                "{} posting/sitemap fetch failure(s) during the Alfred run: {}",
                len(fetch_failures),
                list(fetch_failures)[:5],
            )

        parsed, parse_issues = self._parser.parse_many(raw_jobs)
        # After parsing, not before: the general-application discriminator is the
        # title, and the slug prefix is shared with three real vacancies.
        parsed, dropped = self._drop_general_application(parsed)
        raw_count = len(parsed) + dropped
        report = self._validator.validate([{"slug": j.source_job_id} for j in parsed], parsed)
        cleaned = self._cleaner.clean_jobs(parsed)

        result = AlfredPipelineRunResult(
            raw_count=raw_count,
            parsed_count=len(parsed),
            validation_passed=report.passed,
            cleaned_count=len(cleaned),
            fetch_failures=len(fetch_failures),
            general_application_dropped=dropped,
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
                    "scripts/register_source.py --code alfred ... before scraping."
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
                    logger.warning("failed to persist Alfred job {}: {}", job.source_job_id, exc)
            session.commit()

        logger.info(
            "Alfred run complete: {} inserted, {} updated, {} unchanged, {} failed",
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.failed_count,
        )
        return result

"""scrapers.reed.pipeline
=======================

Automated ETL pipeline for Reed, following the same overall shape
``scrapers/remotive/pipeline.py`` established: Fetching -> Parsing ->
Batch Validation -> Text Cleaning -> Database Storage & Deduplication.
See this module's own docstring sections below for where Reed's shape
genuinely diverges and why — Reed is the first source needing more than
one API call per job, a real per-run request budget, and (for real runs
only) a database read before cleaning even starts, not just at persist
time.

Why this pipeline reads the database BEFORE cleaning, unlike every other source
---------------------------------------------------------------------------------
Reed's Search endpoint can return more jobs than
``ReedSettings.max_jobs_processed_per_run`` allows processing in one run
(a real, expected situation — see ``config.py``'s module docstring).
Deciding WHICH jobs to process within that cap benefits from knowing
which ``source_job_id``s are already in ``core.jobs`` for this source
(via ``JobRepository.get_existing_source_job_ids``): genuinely new jobs
are prioritized first, so a capped run still discovers new postings
rather than only ever re-confirming jobs already captured. This
prioritization is a best-effort optimization, not a correctness
requirement — if the database is unreachable at this point,
``_prioritize_search_results`` logs a warning and falls back to
processing jobs in whatever order Search returned them, rather than
aborting the run. It is also skipped entirely in dry runs (``store_db=False``),
preserving the "a dry run touches no database at all" property every
other pipeline's dry-run path already has.

Why a job that can't get a Details call is deferred entirely, not processed with partial data
-------------------------------------------------------------------------------------------------
An earlier version of this design considered skipping the Details call
for jobs already known to the database, to save requests. That has a real
correctness problem: if a known job's title or salary genuinely changed
since it was last scraped, but its Details refresh was skipped to save a
request, ``JobRepository.save_cleaned_job``'s content-changed UPDATE path
would fire (title/salary aren't part of the "was this job already seen"
check, only of the content hash) and would overwrite that job's
previously-correct ``currency_id``/``pay_period``/``employment_type_id``
with whatever a Details-less ``CleanedJob`` provides — silently
regressing data that was previously right. This pipeline avoids that
class of bug structurally: a job is only ever cleaned and stored once
ITS OWN Details call has actually succeeded THIS run (see
``_fetch_details_for_selected``); a job whose Details call fails, or that
didn't fit within ``max_jobs_processed_per_run`` at all, is left out of
this run's batch entirely and will be reconsidered next run when Search
surfaces it again — never partially processed.

What "what to search for" actually is — mostly resolved, with a real gap this delivery closes
---------------------------------------------------------------------------------------------
``ReedSearchQuery``/``DEFAULT_SEARCH_QUERIES`` (``search_queries.py``)
were not part of the originally confirmed design (field mapping,
``CleanedJob`` diff, ``job_repository`` diff, pipeline shape, request-
budget approach) — see that module's docstring for why. The confirmed
answer (project owner, 2026-09-27) is ``ops.reed_search_queue`` (see
``migrations/add_reed_search_queue_table.sql``): a persistent, claimable
queue seeded with real (keywords, location_name) combinations via
``scripts/seed_reed_queries.py``, NOT the static placeholder list.

Concretely: when ``store_db=True`` and the constructor was NOT given an
explicit ``search_queries`` override, this pipeline claims
``ReedSettings.queries_claimed_per_run`` rows from that queue (via
``db.reed_query_queue_repository.ReedQueryQueueRepository``) instead of
reading ``DEFAULT_SEARCH_QUERIES``, and marks each claimed row `done` or
`failed` once this run's Search calls for it complete. The static
``search_queries`` constructor override still exists and still wins when
given — for tests, and for a deliberate one-off/manual run — and dry runs
(``store_db=False``) never touch the queue, same "a dry run touches no
database at all" property every other pipeline's dry-run path already
has. A queue-sourced run whose queue happens to be empty (not yet seeded)
simply finds zero jobs this run — an honest, logged outcome, not an
error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.reed.client import ReedClient
from job_market_intel.scrapers.reed.config import ReedSettings
from job_market_intel.scrapers.reed.exceptions import ReedError
from job_market_intel.scrapers.reed.parser import ReedParser
from job_market_intel.scrapers.reed.search_queries import DEFAULT_SEARCH_QUERIES, ReedSearchQuery
from job_market_intel.validation import ReedBatchValidator, ReedValidationSettings

if TYPE_CHECKING:
    from job_market_intel.cleaning.reed_cleaner import ReedCleaner
    from job_market_intel.db.job_repository import JobRepository
    from job_market_intel.db.reed_query_queue_repository import (
        ClaimedReedQuery,
        ReedQueryQueueRepository,
    )


class ReedPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Reed pipeline.

    Fields beyond what every other source's ``*PipelineRunResult`` has:
    ``processed_count``, ``deferred_count``, and
    ``details_fetch_failed_count`` — together they account for
    ``raw_count`` (``processed_count + deferred_count +
    details_fetch_failed_count == raw_count`` always holds), making
    visible exactly what happened to every job Search found, not just how
    many made it all the way through.
    """

    queries_searched: int = Field(
        0, description="Search queries run this run (claimed from the queue, or static)."
    )
    raw_count: int = Field(
        ..., description="Unique jobs found across every search query this run (deduplicated)."
    )
    processed_count: int = Field(
        ..., description="Jobs selected for a Details call within this run's per-run cap."
    )
    deferred_count: int = Field(
        0, description="Jobs found but not selected this run (cap reached); retried next run."
    )
    details_fetch_failed_count: int = Field(
        0, description="Jobs selected for processing whose Details call failed this run."
    )
    parsed_count: int = Field(..., description="Jobs successfully parsed into Pydantic models.")
    validation_passed: bool = Field(..., description="Whether batch validation checks passed.")
    cleaned_count: int = Field(..., description="Jobs cleaned and normalized.")
    inserted_count: int = Field(0, description="New jobs inserted into PostgreSQL.")
    updated_count: int = Field(0, description="Existing jobs updated in PostgreSQL.")
    unchanged_count: int = Field(0, description="Jobs skipped (identical SHA-256 content hash).")
    failed_count: int = Field(0, description="Jobs that failed DB persistence.")
    session_id: int | None = Field(None, description="ops.scraping_sessions session_id if stored.")
    issues: list[str] = Field(default_factory=list, description="Validation issues, if any.")


class ReedPipeline:
    """Automated end-to-end pipeline runner for the Reed scraper."""

    def __init__(
        self,
        settings: ReedSettings | None = None,
        validation_settings: ReedValidationSettings | None = None,
        client: ReedClient | None = None,
        parser: ReedParser | None = None,
        validator: ReedBatchValidator | None = None,
        cleaner: ReedCleaner | None = None,
        repository: JobRepository | None = None,
        search_queries: list[ReedSearchQuery] | None = None,
        queue_repository: ReedQueryQueueRepository | None = None,
    ) -> None:
        self.settings = settings or ReedSettings()
        self.client = client or ReedClient(settings=self.settings)
        self.parser = parser or ReedParser()
        self.validator = validator or ReedBatchValidator(
            settings=validation_settings or ReedValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.reed_cleaner import ReedCleaner

            cleaner = ReedCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

        if queue_repository is None:
            from job_market_intel.db.reed_query_queue_repository import ReedQueryQueueRepository

            queue_repository = ReedQueryQueueRepository()
        self.queue_repository = queue_repository

        # An explicit search_queries always wins over the queue (tests,
        # one-off manual runs) -- see this module's docstring. When not
        # given, dry runs fall back to the placeholder DEFAULT list and
        # real runs (store_db=True) claim from ops.reed_search_queue.
        self._explicit_search_queries = search_queries is not None
        self.search_queries = (
            search_queries if search_queries is not None else DEFAULT_SEARCH_QUERIES
        )

    def run(
        self, *, store_db: bool = True, session_override: Any | None = None
    ) -> ReedPipelineRunResult:
        """Run the Reed pipeline end-to-end.

        Args:
            store_db: If True, persist cleaned jobs into PostgreSQL, and
                use the database to prioritize which jobs get processed
                first if this run's search results exceed
                ``ReedSettings.max_jobs_processed_per_run``.
            session_override: Optional SQLAlchemy Session for testing /
                custom transaction context. Used for both the
                prioritization read and the persistence write when
                given.

        Returns:
            ReedPipelineRunResult with execution metrics.
        """
        claimed: list[ClaimedReedQuery] | None = None
        if store_db and not self._explicit_search_queries:
            claimed = self._claim_queries_from_queue(session_override)
            queries = [item.search_query for item in claimed]
            if not queries:
                logger.warning(
                    "No queries claimed from ops.reed_search_queue this run -- the "
                    "queue may be empty or unseeded (see scripts/seed_reed_queries.py)."
                )
        else:
            queries = self.search_queries
            if not self._explicit_search_queries:
                logger.warning(
                    "Dry run using the PLACEHOLDER default search query ({!r}); "
                    "real runs claim from ops.reed_search_queue instead.",
                    queries,
                )

        logger.info(
            "Starting Reed automated pipeline run (store_db={}, {} quer{}).",
            store_db,
            len(queries),
            "y" if len(queries) == 1 else "ies",
        )

        all_search_results, outcomes = self._fetch_all_search_results(queries)
        if claimed is not None:
            self._mark_claimed_queries(claimed, outcomes, session_override)

        ordered = all_search_results
        if store_db:
            ordered = self._prioritize_search_results(all_search_results, session_override)

        selected, deferred = self._select_within_cap(ordered)
        combined, details_failed_count = self._fetch_details_for_selected(selected)
        parsed_jobs = self.parser.parse_jobs(combined)
        validation_report = self.validator.validate(combined, parsed_jobs)
        cleaned_jobs = self.cleaner.clean_jobs(parsed_jobs)

        result = ReedPipelineRunResult(
            queries_searched=len(queries),
            raw_count=len(all_search_results),
            processed_count=len(selected),
            deferred_count=len(deferred),
            details_fetch_failed_count=details_failed_count,
            parsed_count=len(parsed_jobs),
            validation_passed=validation_report.passed,
            cleaned_count=len(cleaned_jobs),
            issues=validation_report.issues,
        )

        if not store_db:
            logger.info("Pipeline dry-run completed (store_db=False).")
            return result

        if session_override is not None:
            self._persist_with_session(session_override, cleaned_jobs, result)
        else:
            try:
                with get_session() as session:
                    self._persist_with_session(session, cleaned_jobs, result)
            except Exception as exc:
                logger.error("Failed to connect or persist to PostgreSQL database: {}", exc)

        return result

    def _claim_queries_from_queue(self, session_override: Any | None) -> list[ClaimedReedQuery]:
        """Claim this run's queries from ops.reed_search_queue.

        Best-effort: a database failure here is logged and yields an
        empty list (nothing to search this run), rather than crashing.
        """
        limit = self.settings.queries_claimed_per_run
        try:
            if session_override is not None:
                return self.queue_repository.claim_next_queries(session_override, limit)
            with get_session() as session:
                return self.queue_repository.claim_next_queries(session, limit)
        except Exception as exc:
            logger.error("Could not claim queries from ops.reed_search_queue: {}", exc)
            return []

    def _mark_claimed_queries(
        self,
        claimed: list[ClaimedReedQuery],
        outcomes: list[tuple[bool, str | None]],
        session_override: Any | None,
    ) -> None:
        """Mark each claimed queue row done/failed. Best-effort, never raises."""

        def _mark_all(session: Any) -> None:
            for item, (succeeded, error) in zip(claimed, outcomes, strict=True):
                self.queue_repository.mark_query_result(
                    session,
                    item.query_id,
                    status="done" if succeeded else "failed",
                    error=error,
                )

        try:
            if session_override is not None:
                _mark_all(session_override)
            else:
                with get_session() as session:
                    _mark_all(session)
        except Exception as exc:
            logger.error("Could not mark claimed Reed queries done/failed: {}", exc)

    def _fetch_all_search_results(
        self, queries: list[ReedSearchQuery]
    ) -> tuple[list[dict], list[tuple[bool, str | None]]]:
        """Fetch and aggregate Search results across the given queries.

        Deduplicates by ``jobId`` globally (not per query) for two
        confirmed reasons, not just one: a job can legitimately match
        more than one query (e.g. "data scientist" and "AI engineer" both
        matching the same posting) -- AND, confirmed live during a real
        1000-result run against a SINGLE query, Reed's own pagination can
        return the same job twice across different ``resultsToSkip``
        pages within one query (1000 raw Search results, 958 unique --
        42 duplicates from one query alone, likely from the underlying
        live listing shifting slightly between page fetches). Either way,
        each unique job should only be processed (and cost one Details
        call) once per run -- confirming ``seen_job_ids`` needs to be
        shared across the whole method, not reset per query.

        A ReedError on one query's Search is logged and that query is
        recorded as failed; the remaining queries still run (same
        skip-don't-crash philosophy as per-job Details failures). A bad
        API key is the exception in spirit -- it fails every query the
        same way, and each is honestly recorded as failed.

        Returns:
            ``(deduplicated_jobs, outcomes)`` where ``outcomes`` has one
            ``(succeeded, error_message)`` entry per query, in the same
            order as ``queries``.
        """
        seen_job_ids: set[Any] = set()
        deduplicated: list[dict] = []
        outcomes: list[tuple[bool, str | None]] = []
        for query in queries:
            try:
                results = self.client.fetch_search_results(query)
            except ReedError as exc:
                logger.warning("Reed Search failed for query {!r}: {}", query, exc)
                outcomes.append((False, str(exc)))
                continue
            outcomes.append((True, None))
            for job in results:
                job_id = job.get("jobId")
                if job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                deduplicated.append(job)
        logger.info(
            "Fetched {} unique jobs across {} search quer{}.",
            len(deduplicated),
            len(queries),
            "y" if len(queries) == 1 else "ies",
        )
        return deduplicated, outcomes

    def _prioritize_search_results(
        self, search_results: list[dict], session_override: Any | None
    ) -> list[dict]:
        """Reorder search results so genuinely new jobs are processed first.

        Best-effort: any failure to reach the database here is logged and
        falls back to the original (unordered) list, rather than aborting
        the run -- see this module's docstring.
        """
        try:
            if session_override is not None:
                return self._compute_priority_order(session_override, search_results)
            with get_session() as session:
                return self._compute_priority_order(session, search_results)
        except Exception as exc:
            logger.warning(
                "Could not prioritize Reed search results against the database ({}); "
                "processing in the order Search returned them instead.",
                exc,
            )
            return search_results

    def _compute_priority_order(self, session: Any, search_results: list[dict]) -> list[dict]:
        source_id = self.repository.get_source_id_by_code(session, "reed")
        candidate_ids = [str(job["jobId"]) for job in search_results]
        existing_ids = self.repository.get_existing_source_job_ids(
            session, source_id, candidate_ids
        )
        new_jobs = [job for job in search_results if str(job["jobId"]) not in existing_ids]
        known_jobs = [job for job in search_results if str(job["jobId"]) in existing_ids]
        return new_jobs + known_jobs

    def _select_within_cap(self, ordered: list[dict]) -> tuple[list[dict], list[dict]]:
        cap = self.settings.max_jobs_processed_per_run
        selected, deferred = ordered[:cap], ordered[cap:]
        if deferred:
            logger.warning(
                "Reed search found {} jobs; only processing {} this run "
                "(max_jobs_processed_per_run={}). The remaining {} will be "
                "reconsidered next run.",
                len(ordered),
                len(selected),
                cap,
                len(deferred),
            )
        return selected, deferred

    def _fetch_details_for_selected(self, selected: list[dict]) -> tuple[list[dict], int]:
        """Fetch Details for every selected job, skipping (not degrading) any that fail.

        Returns:
            A ``(combined, failed_count)`` tuple. ``combined`` contains
            one ``{"search": ..., "details": ...}`` entry per job whose
            Details call succeeded -- see this module's docstring for why
            a failed Details call means the job is skipped for this run
            entirely, not included with ``details=None``.
        """
        combined: list[dict] = []
        failed_count = 0
        for job in selected:
            job_id = str(job["jobId"])
            try:
                details = self.client.fetch_job_details(job_id)
            except ReedError as exc:
                failed_count += 1
                logger.warning(
                    "Skipping Reed job {} this run -- Details fetch failed: {}", job_id, exc
                )
                continue
            combined.append({"search": job, "details": details})
        return combined, failed_count

    def _persist_with_session(
        self,
        session: Any,
        cleaned_jobs: list[Any],
        result: ReedPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "reed")
        session_id = self.repository.create_scraping_session(
            session, source_id=source_id, trigger_type="manual"
        )
        result.session_id = session_id

        counts = self.repository.save_cleaned_jobs(
            session=session,
            jobs=cleaned_jobs,
            source_id=source_id,
            session_id=session_id,
        )

        result.inserted_count = counts["inserted"]
        result.updated_count = counts["updated"]
        result.unchanged_count = counts["unchanged"]
        result.failed_count = counts["failed"]

        status = "completed" if counts["failed"] == 0 else "partial"
        self.repository.finish_scraping_session(
            session=session,
            session_id=session_id,
            status=status,
            jobs_found=result.raw_count,
            jobs_new=counts["inserted"],
            jobs_updated=counts["updated"],
            jobs_failed=counts["failed"],
            # Approximate: the real number of Search API calls made
            # depends on pagination per query (see client.py), which
            # isn't threaded back up to this layer -- number of
            # configured queries is a rough, honestly-approximate stand-
            # in, not a precise page count.
            pages_scraped=result.queries_searched,
        )

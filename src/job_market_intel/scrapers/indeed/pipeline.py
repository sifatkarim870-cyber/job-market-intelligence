"""scrapers.indeed.pipeline
=========================

Orchestrates one Indeed scraping run: claim the next due
``ops.scrape_query_queue`` row -> run a bounded, paced browser session
against it (search pages, then detail pages within their own caps) ->
validate -> clean -> persist -> record how the queue item's session ended.

Structurally different from remoteok/pipeline.py in one deliberate way:
this brackets the browser phase between two short-lived DB sessions
(claim, then persist+record) rather than holding one session open for the
whole run. A Selenium session against Indeed is expected to run for
minutes (pacing/long-pause delays alone can add up to several minutes per
run — see config.py), and holding a PostgreSQL connection open and idle
for that whole window for no reason would be a real, avoidable liability
under a scheduler meant to run this for years. See ``run()`` below for
where each session opens and closes.

Blocking is handled at this layer, not swallowed: IndeedBlockedError
(challenge detected, or max_consecutive_failures reached) ends the browser
phase immediately, but whatever records were already collected before the
block are still cleaned and persisted — "scrape everything possible"
means partial progress from a cut-short session has real value, not that
a block should be retried into a worse block within the same run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

from job_market_intel.db.session import get_session
from job_market_intel.scrapers.indeed.client import IndeedClient
from job_market_intel.scrapers.indeed.config import IndeedSettings
from job_market_intel.scrapers.indeed.exceptions import IndeedBlockedError, IndeedFetchError
from job_market_intel.scrapers.indeed.models import RawIndeedJob
from job_market_intel.scrapers.indeed.parser import parse_detail_page, parse_search_page
from job_market_intel.validation.indeed_validator import (
    IndeedBatchValidator,
    IndeedValidationSettings,
)

if TYPE_CHECKING:
    from job_market_intel.cleaning.indeed_cleaner import IndeedCleaner
    from job_market_intel.db.job_repository import JobRepository
    from job_market_intel.db.scrape_queue_repository import ScrapeQueueRepository


class IndeedPipelineRunResult(BaseModel):
    """Execution summary for a single run of the Indeed pipeline."""

    query_text: str | None = Field(default=None, description="Queue item worked this run, if any.")
    location_text: str | None = Field(default=None, description="Queue item's location, if any.")
    queue_empty: bool = Field(default=False, description="True if no queue row was eligible.")
    search_pages_visited: int = 0
    detail_pages_visited: int = 0
    raw_count: int = Field(default=0, description="Total cards extracted from visited pages.")
    parsed_count: int = Field(default=0, description="Cards successfully parsed into models.")
    validation_passed: bool = True
    cleaned_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    session_id: int | None = Field(default=None, description="ops.scraping_sessions id if stored.")
    queue_status: str | None = Field(default=None, description="'pending' | 'done' | 'failed'.")
    blocked_reason: str | None = Field(default=None, description="Set if IndeedBlockedError fired.")
    issues: list[str] = Field(default_factory=list, description="Validation issues, if any.")


class IndeedPipeline:
    """Automated end-to-end pipeline runner for the Indeed scraper."""

    def __init__(
        self,
        settings: IndeedSettings | None = None,
        validation_settings: IndeedValidationSettings | None = None,
        client: IndeedClient | None = None,
        validator: IndeedBatchValidator | None = None,
        cleaner: IndeedCleaner | None = None,
        repository: JobRepository | None = None,
        queue_repository: ScrapeQueueRepository | None = None,
    ) -> None:
        self.settings = settings or IndeedSettings()
        self.client = client or IndeedClient(settings=self.settings)
        self.validator = validator or IndeedBatchValidator(
            settings=validation_settings or IndeedValidationSettings()
        )
        if cleaner is None:
            from job_market_intel.cleaning.indeed_cleaner import IndeedCleaner

            cleaner = IndeedCleaner()
        self.cleaner = cleaner

        if repository is None:
            from job_market_intel.db.job_repository import JobRepository

            repository = JobRepository()
        self.repository = repository

        if queue_repository is None:
            from job_market_intel.db.scrape_queue_repository import ScrapeQueueRepository

            queue_repository = ScrapeQueueRepository()
        self.queue_repository = queue_repository

    def run(self, *, store_db: bool = True) -> IndeedPipelineRunResult:
        """Run one Indeed pipeline cycle end-to-end.

        Args:
            store_db: If True, persist cleaned jobs and record the queue
                outcome. If False (dry-run), the browser phase and
                cleaning still run in full — only persistence is skipped —
                so ``--no-db`` is still a genuine end-to-end test of the
                scraping/parsing/cleaning logic, matching this project's
                dry-run-first convention. Note the queue item is still
                *claimed* (marked in_progress) even in a dry-run, since
                claiming requires a DB write to be meaningful at all;
                dry-run only skips the final persist+record step, leaving
                that row 'in_progress' for a manual reset. This is a
                known, accepted asymmetry for --no-db runs specifically.

        Returns:
            IndeedPipelineRunResult with execution metrics.
        """
        result = IndeedPipelineRunResult()

        with get_session() as session:
            source_id = self.repository.get_source_id_by_code(session, "indeed")
            claimed = self.queue_repository.claim_next_query(session, source_id)

        if claimed is None:
            logger.warning(
                "indeed.pipeline.queue_empty - nothing eligible in ops.scrape_query_queue "
                "for source_id={}. Seed it first (scripts/seed_indeed_queries.py).",
                source_id,
            )
            result.queue_empty = True
            return result

        result.query_text = claimed.query_text
        result.location_text = claimed.location_text
        logger.info(
            "indeed.pipeline.claimed query={!r} location={!r} resume_from_page={}",
            claimed.query_text,
            claimed.location_text,
            claimed.last_page_reached + 1,
        )

        raw_jobs, final_page_reached, queue_status, blocked_reason = self._run_browser_phase(
            query_text=claimed.query_text,
            location_text=claimed.location_text,
            resume_from_page=claimed.last_page_reached + 1,
        )
        result.search_pages_visited = self.client.search_pages_visited
        result.detail_pages_visited = self.client.detail_pages_visited
        result.raw_count = len(raw_jobs)
        result.parsed_count = len(raw_jobs)
        result.queue_status = queue_status
        result.blocked_reason = blocked_reason

        validation_report = self.validator.validate(
            raw_cards=[job.raw_payload for job in raw_jobs], parsed_jobs=raw_jobs
        )
        result.validation_passed = validation_report.passed
        result.issues = validation_report.issues

        cleaned_jobs = self.cleaner.clean_jobs(raw_jobs)
        result.cleaned_count = len(cleaned_jobs)

        if not store_db:
            logger.info("indeed.pipeline.dry_run_complete store_db=False")
            return result

        try:
            with get_session() as session:
                self._persist_and_record(
                    session,
                    cleaned_jobs=cleaned_jobs,
                    raw_count=len(raw_jobs),
                    query_id=claimed.query_id,
                    final_page_reached=final_page_reached,
                    queue_status=queue_status,
                    blocked_reason=blocked_reason,
                    result=result,
                )
        except Exception as exc:  # noqa: BLE001 - matches remoteok/pipeline.py's
            # own top-level persistence guard; a DB failure here must not
            # crash the scheduler process, only this run.
            logger.error("indeed.pipeline.persist_failed error={}", exc)

        return result

    def _run_browser_phase(
        self, *, query_text: str, location_text: str, resume_from_page: int
    ) -> tuple[list[RawIndeedJob], int, str, str | None]:
        """Runs the paced, capped browser session. Returns (collected
        records, last search page successfully parsed, queue_status,
        blocked_reason). Never raises — IndeedBlockedError is caught here
        and turned into queue_status='failed' with the reason recorded,
        so callers never need their own try/except for it.
        """
        raw_jobs: list[RawIndeedJob] = []
        attempted_detail_ids: set[str] = set()
        page_number = resume_from_page
        last_completed_page = resume_from_page - 1
        consecutive_failures = 0
        blocked_reason: str | None = None

        self.client.open_session()
        try:
            try:
                page_source = self._first_page_or_none(query_text, location_text, resume_from_page)
            except IndeedFetchError as exc:
                # Unlike a mid-loop next-page failure (which tolerates
                # max_consecutive_failures - 1 retries before giving up —
                # see below), failing to load the very first/resume page
                # at all means there is nothing to fall back to within
                # this session. Treated as an immediate block rather than
                # forced through the same counter, so this doesn't
                # silently need max_consecutive_failures=1 to behave
                # sensibly.
                raise IndeedBlockedError(f"failed to load initial page: {exc}") from exc

            while True:
                if page_source is None:
                    break  # end of results for this query/location

                if self.client.detect_challenge(page_source):
                    raise IndeedBlockedError(f"challenge detected on search page {page_number}")

                page_cards = parse_search_page(
                    page_source,
                    query_text=query_text,
                    location_text=location_text,
                    search_page_number=page_number,
                )
                raw_jobs.extend(page_cards)
                last_completed_page = page_number
                consecutive_failures = 0

                self._fill_in_descriptions(raw_jobs, attempted_detail_ids)

                if self.client.search_pages_visited >= self.settings.max_search_pages_per_session:
                    logger.info("indeed.pipeline.session_page_cap_reached page={}", page_number)
                    break

                page_number += 1
                page_source, consecutive_failures = self._fetch_next_page_with_retries(
                    consecutive_failures
                )

            queue_status = "done" if page_source is None else "pending"
        except IndeedBlockedError as exc:
            blocked_reason = str(exc)
            queue_status = "failed"
            logger.error("indeed.pipeline.blocked reason={}", blocked_reason)
        finally:
            self.client.close_session()

        return raw_jobs, last_completed_page, queue_status, blocked_reason

    def _fetch_next_page_with_retries(self, consecutive_failures: int) -> tuple[str | None, int]:
        """Calls go_to_next_search_page(), retrying in place (not advancing
        past the failure) until it either succeeds/returns None (real end
        of results) or consecutive_failures reaches
        max_consecutive_failures, which raises IndeedBlockedError.

        Pulled out of the main loop specifically because the earlier
        version of this logic had a real bug: treating a single transient
        fetch failure as "no more pages" ended the session silently
        marked 'done' after exactly one failure, never actually reaching
        max_consecutive_failures however low it was configured. Retrying
        in place is what makes that threshold mean what its name says.
        """
        while True:
            try:
                page_source = self.client.go_to_next_search_page()
                return page_source, 0
            except IndeedFetchError:
                consecutive_failures += 1
                logger.warning(
                    "indeed.pipeline.page_fetch_failed consecutive={}", consecutive_failures
                )
                if consecutive_failures >= self.settings.max_consecutive_failures:
                    raise IndeedBlockedError(
                        f"{consecutive_failures} consecutive fetch failures"
                    ) from None

    def _first_page_or_none(
        self, query_text: str, location_text: str, resume_from_page: int
    ) -> str | None:
        """Loads page 1 always (there's no ?start=N URL to resume directly
        onto — see client.py's module docstring on why pagination is
        click-driven, not URL-driven), then clicks forward to
        resume_from_page if this queue item previously made progress.
        Returns None (rather than raising) only if a resumed query
        immediately runs out of pages, e.g. Indeed now has fewer pages of
        results than it did last time this combination was worked.
        """
        page_source: str | None = self.client.open_search(query_text, location_text)
        pages_to_skip = resume_from_page - 1
        for _ in range(pages_to_skip):
            if page_source is None or self.client.detect_challenge(page_source):
                return page_source
            page_source = self.client.go_to_next_search_page()
        return page_source

    def _fill_in_descriptions(
        self, raw_jobs: list[RawIndeedJob], attempted_detail_ids: set[str]
    ) -> None:
        """Visits detail pages for organic (non-sponsored) records that
        haven't been attempted yet this session, up to
        max_detail_pages_per_session. Mutates raw_jobs in place (Pydantic
        models are replaced, not edited, since RawIndeedJob has no
        mutation API by design — see models.py). Called after each search
        page so the detail-page cap is respected incrementally rather than
        all at once at the end, keeping a session's actual page/detail mix
        closer to what pacing assumed.

        attempted_detail_ids tracks every source_job_id this method has
        ever tried, independent of whether a description was actually
        extracted. This exists because of a real bug caught on the first
        live run: using `description_raw is not None` alone as the
        "already handled" signal meant a job whose detail page loaded but
        whose description container wasn't found (parse_detail_page
        returning None — see that function) had no way to be marked done,
        so the next search page's call to this same method re-visited it
        again. On a 2-page, 16-job run that produced 21 detail-page
        visits — wasted requests against exactly the traffic this project
        is trying hardest to keep unremarkable. attempted_detail_ids is
        the fix: every job is visited at most once per session regardless
        of outcome.
        """
        for index, job in enumerate(raw_jobs):
            if job.detail_url is None or job.source_job_id in attempted_detail_ids:
                continue
            if self.client.detail_pages_visited >= self.settings.max_detail_pages_per_session:
                break
            attempted_detail_ids.add(job.source_job_id)
            try:
                detail_source = self.client.open_detail_in_new_tab(job.detail_url)
            except IndeedFetchError:
                logger.warning("indeed.pipeline.detail_fetch_failed url={}", job.detail_url)
                continue
            if self.client.detect_challenge(detail_source):
                raise IndeedBlockedError(f"challenge detected on detail page {job.detail_url}")
            description = parse_detail_page(detail_source)
            if description is not None:
                raw_jobs[index] = job.model_copy(update={"description_raw": description})

    def _persist_and_record(
        self,
        session: Any,
        *,
        cleaned_jobs: list[Any],
        raw_count: int,
        query_id: int,
        final_page_reached: int,
        queue_status: str,
        blocked_reason: str | None,
        result: IndeedPipelineRunResult,
    ) -> None:
        source_id = self.repository.get_source_id_by_code(session, "indeed")
        scraping_session_id = self.repository.create_scraping_session(
            session, source_id=source_id, trigger_type="manual"
        )
        result.session_id = scraping_session_id

        counts = self.repository.save_cleaned_jobs(
            session=session,
            jobs=cleaned_jobs,
            source_id=source_id,
            session_id=scraping_session_id,
        )
        result.inserted_count = counts["inserted"]
        result.updated_count = counts["updated"]
        result.unchanged_count = counts["unchanged"]
        result.failed_count = counts["failed"]

        status = "completed" if counts["failed"] == 0 else "partial"
        self.repository.finish_scraping_session(
            session=session,
            session_id=scraping_session_id,
            status=status if queue_status != "failed" else "failed",
            jobs_found=raw_count,
            jobs_new=counts["inserted"],
            jobs_updated=counts["updated"],
            jobs_failed=counts["failed"],
            pages_scraped=self.client.search_pages_visited,
        )

        self.queue_repository.mark_query_result(
            session,
            query_id,
            status=queue_status,
            last_page_reached=final_page_reached,
            error=blocked_reason,
        )

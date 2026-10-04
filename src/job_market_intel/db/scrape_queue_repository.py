"""db.scrape_queue_repository
============================

Repository for ops.scrape_query_queue — the persistent work queue
scrapers/indeed/pipeline.py claims from to know which (query, location)
combination to work next, and updates when a session ends.

Follows job_repository.py's own established pattern exactly (raw SQL via
`text()` against a caller-supplied `Session`, no ORM model — see
JobRepository's `model = None` override and its docstring for why this
project isn't using AbstractRepository's `model: type[T]` contract): same
`AbstractRepository[Any]` base, same override, same "methods take Session
explicitly, never commit internally" contract, so this composes into
whatever `get_session()` / `transaction()` unit of work the caller is
already in, exactly like JobRepository does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from job_market_intel.db.exceptions import RepositoryError
from job_market_intel.db.repository import AbstractRepository


@dataclass(frozen=True)
class ClaimedQuery:
    """One claimed row from ops.scrape_query_queue, ready to be worked."""

    query_id: int
    query_text: str
    location_text: str
    last_page_reached: int


class ScrapeQueueRepository(AbstractRepository[Any]):
    """Repository for ops.scrape_query_queue."""

    # Same deliberate deviation as JobRepository — this repository issues
    # raw SQL against one table with no ORM model, so `model: type[T]`
    # has no meaningful value. See job_repository.py's identical comment.
    model = None  # type: ignore[assignment]

    def __init__(self) -> None:
        pass

    def get_by_id(self, session: Session, entity_id: Any) -> Any | None:
        row = session.execute(
            text(
                "SELECT query_id, source_id, query_text, location_text, status, "
                "last_page_reached FROM ops.scrape_query_queue WHERE query_id = :query_id"
            ),
            {"query_id": entity_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_all(self, session: Session, *, limit: int = 100, offset: int = 0) -> list[Any]:
        rows = session.execute(
            text(
                "SELECT query_id, source_id, query_text, location_text, status, "
                "last_page_reached FROM ops.scrape_query_queue "
                "ORDER BY query_id LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        ).all()
        return [dict(r._mapping) for r in rows]

    def add(self, session: Session, entity: Any) -> Any:
        raise NotImplementedError("Use seed_query instead.")

    def update(self, session: Session, entity: Any) -> Any:
        raise NotImplementedError("Use mark_query_result instead.")

    def delete(self, session: Session, entity: Any) -> None:
        if isinstance(entity, int):
            session.execute(
                text("DELETE FROM ops.scrape_query_queue WHERE query_id = :query_id"),
                {"query_id": entity},
            )

    def count(self, session: Session) -> int:
        return session.execute(text("SELECT count(*) FROM ops.scrape_query_queue")).scalar() or 0

    # --- Queue-specific operations ---------------------------------------

    def seed_query(
        self, session: Session, source_id: int, query_text_: str, location_text: str
    ) -> None:
        """Insert a (query, location) combination if it isn't already
        queued for this source. Safe to call repeatedly with the same
        combination — the unique constraint makes this idempotent, unlike
        a plain INSERT.
        """
        session.execute(
            text(
                "INSERT INTO ops.scrape_query_queue (source_id, query_text, location_text) "
                "VALUES (:source_id, :query_text, :location_text) "
                "ON CONFLICT (source_id, query_text, location_text) DO NOTHING"
            ),
            {"source_id": source_id, "query_text": query_text_, "location_text": location_text},
        )

    def claim_next_queries(
        self, session: Session, source_id: int, limit: int
    ) -> list[ClaimedQuery]:
        """Same eligibility and locking semantics as claim_next_query above
        (pending/done only, FOR UPDATE SKIP LOCKED, oldest-due first) but
        claims up to `limit` rows in one atomic round trip instead of one
        — added once the seeded queue grew to ~21,000 combinations
        (every country x a broad job-title set) and one-item-per-run
        stopped being enough to make real progress against it. See
        IndeedSettings.items_per_run's docstring for the full reasoning.

        Returns fewer than `limit` (including an empty list) if that many
        eligible rows don't exist — never an error, same as
        claim_next_query returning None for the single-row case.
        """
        rows = session.execute(
            text(
                "WITH claimed AS ("
                "  SELECT query_id FROM ops.scrape_query_queue "
                "  WHERE source_id = :source_id AND status IN ('pending', 'done') "
                "  ORDER BY last_scraped_at NULLS FIRST, query_id "
                "  LIMIT :limit "
                "  FOR UPDATE SKIP LOCKED"
                ") "
                "UPDATE ops.scrape_query_queue q SET status = 'in_progress' "
                "FROM claimed c WHERE q.query_id = c.query_id "
                "RETURNING q.query_id, q.query_text, q.location_text, q.last_page_reached"
            ),
            {"source_id": source_id, "limit": limit},
        ).all()
        return [
            ClaimedQuery(
                query_id=row.query_id,
                query_text=row.query_text,
                location_text=row.location_text,
                last_page_reached=row.last_page_reached,
            )
            for row in rows
        ]

    def claim_next_query(self, session: Session, source_id: int) -> ClaimedQuery | None:
        """Atomically claim the queue's next-most-due row for this source
        (oldest `last_scraped_at`, NULLs — i.e. never attempted — first)
        and mark it `in_progress`, or return None if nothing is eligible.

        `FOR UPDATE SKIP LOCKED` matters even though this project runs one
        scheduled Indeed job at a time today: it's the standard, cheap-to-
        write safeguard against two runs ever claiming the same row if the
        scheduler is ever changed to allow overlap, and it costs nothing
        when there's no contention.

        Only `pending` and `done` rows are eligible — `done` is included
        deliberately, since Indeed itself adds new postings to a query
        over time; a queue item reaching its own last page once doesn't
        mean it stays exhausted forever (see the migration's COMMENT ON
        ops.scrape_query_queue.status for the same point). `in_progress`
        and `failed` rows are never auto-reclaimed here — see this
        module's docstring: a stuck `in_progress` row indicates a crashed
        run and needs a deliberate manual reset, not silent reclaiming
        that could mask a real problem.
        """
        row = session.execute(
            text(
                "UPDATE ops.scrape_query_queue SET status = 'in_progress' "
                "WHERE query_id = ("
                "  SELECT query_id FROM ops.scrape_query_queue "
                "  WHERE source_id = :source_id AND status IN ('pending', 'done') "
                "  ORDER BY last_scraped_at NULLS FIRST, query_id "
                "  LIMIT 1 "
                "  FOR UPDATE SKIP LOCKED"
                ") "
                "RETURNING query_id, query_text, location_text, last_page_reached"
            ),
            {"source_id": source_id},
        ).first()
        if row is None:
            return None
        return ClaimedQuery(
            query_id=row.query_id,
            query_text=row.query_text,
            location_text=row.location_text,
            last_page_reached=row.last_page_reached,
        )

    def mark_query_result(
        self,
        session: Session,
        query_id: int,
        *,
        status: str,
        last_page_reached: int,
        error: str | None = None,
    ) -> None:
        """Record how a claimed query's session ended.

        status must be one of 'pending' (page cap hit, or the run was
        blocked, but more results remain — resume next run), 'done'
        (parser reached the last page), or 'failed'. Raises
        RepositoryError on an invalid status rather than letting a typo
        silently violate the table's own CHECK constraint with a less
        legible database error.

        Note that 'pending' covers a *blocked* run as well as a page-cap
        run, on purpose. A block is Indeed refusing the egress IP for a
        while, not a defect in the row, and nothing here ever reclaims a
        'failed' row — so recording blocks as 'failed' deleted one queue
        row per blocked run. See IndeedPipeline._run_browser_phase.
        """
        if status not in ("pending", "done", "failed"):
            raise RepositoryError(
                f"mark_query_result got status={status!r}; must be one of "
                "'pending', 'done', 'failed'."
            )
        session.execute(
            text(
                "UPDATE ops.scrape_query_queue SET "
                "status = :status, "
                "last_page_reached = :last_page_reached, "
                "last_scraped_at = now(), "
                "last_error = :error "
                "WHERE query_id = :query_id"
            ),
            {
                "status": status,
                "last_page_reached": last_page_reached,
                "error": error,
                "query_id": query_id,
            },
        )

    def release_claimed_queries(self, session: Session, query_ids: list[int]) -> None:
        """Return rows claimed via claim_next_queries but never worked
        back to 'pending' — used when a run claims a batch but stops
        early on a controlled block (see IndeedPipeline.run), so the
        unworked rows don't stay stuck 'in_progress'. Deliberately does
        NOT touch last_scraped_at or last_page_reached: an item that
        was never attempted has no new scrape outcome to record.
        """
        if not query_ids:
            return
        session.execute(
            text(
                "UPDATE ops.scrape_query_queue SET status = 'pending' "
                "WHERE status = 'in_progress' AND query_id IN :query_ids"
            ).bindparams(bindparam("query_ids", expanding=True)),
            {"query_ids": query_ids},
        )

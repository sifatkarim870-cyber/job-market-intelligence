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

from sqlalchemy import text
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

        status must be one of 'pending' (session's page cap was hit but
        more results remain — resume next run), 'done' (parser reached
        the last page), or 'failed' (session hit IndeedBlockedError; see
        `error`). Raises RepositoryError on an invalid status rather than
        letting a typo silently violate the table's own CHECK constraint
        with a less legible database error.
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

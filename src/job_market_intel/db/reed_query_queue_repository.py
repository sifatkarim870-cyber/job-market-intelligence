"""db.reed_query_queue_repository
================================

Repository for ops.reed_search_queue — the persistent, claimable work
queue scrapers/reed/pipeline.py claims from to decide which (keywords,
location_name) combination(s) to search each run, instead of reading a
static in-code list.

A trimmed-down sibling of db.scrape_queue_repository.ScrapeQueueRepository
(Indeed's own, separate queue), not a copy — no source_id column (this
table only ever holds Reed rows by construction) and no last_page_reached
column (Reed's own pagination fully exhausts a query within one run,
bounded by ReedSettings.max_search_pages_per_query, so there is no
cross-run mid-query resumption state to track the way Indeed's Selenium
sessions need). See migrations/add_reed_search_queue_table.sql's header
comment for the fuller rationale on why this is a separate table, not a
shared one — confirmed with the project owner, not assumed.

Follows job_repository.py's/scrape_queue_repository.py's own established
pattern exactly: raw SQL via `text()` against a caller-supplied `Session`,
no ORM model (see `model = None` below and AbstractRepository's docstring
for why this project's repositories generally don't use the `model:
type[T]` contract), methods take Session explicitly and never commit
internally.

'' (empty string) <-> None convention
---------------------------------------
ops.reed_search_queue.keywords/location_name are NOT NULL TEXT columns
with a '' default, not nullable ones — see the migration's own column
comments for why (PostgreSQL UNIQUE constraints treat NULL as distinct
from any other NULL, which would let duplicate "no filter" rows
accumulate silently). This repository is the one place that translation
happens: '' from the database becomes None on a ReedSearchQuery, and
None on a ReedSearchQuery becomes '' when seeding. Callers (pipeline.py)
never need to know the storage-layer convention exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.db.exceptions import RepositoryError
from job_market_intel.db.repository import AbstractRepository
from job_market_intel.scrapers.reed.search_queries import ReedSearchQuery


@dataclass(frozen=True)
class ClaimedReedQuery:
    """One claimed row from ops.reed_search_queue, ready to be searched."""

    query_id: int
    search_query: ReedSearchQuery


def _to_stored(value: str | None) -> str:
    """None -> '' for storage. See module docstring's '' <-> None convention."""
    return value or ""


def _to_query_value(value: str) -> str | None:
    """'' -> None when building a ReedSearchQuery. See module docstring."""
    return value or None


class ReedQueryQueueRepository(AbstractRepository[Any]):
    """Repository for ops.reed_search_queue."""

    # Same deliberate deviation as JobRepository/ScrapeQueueRepository —
    # this repository issues raw SQL against one table with no ORM model,
    # so `model: type[T]` has no meaningful value. See job_repository.py's
    # identical comment.
    model = None  # type: ignore[assignment]

    def __init__(self) -> None:
        pass

    def get_by_id(self, session: Session, entity_id: Any) -> Any | None:
        row = session.execute(
            text(
                "SELECT query_id, keywords, location_name, distance_from_location, "
                "status, last_scraped_at, last_error FROM ops.reed_search_queue "
                "WHERE query_id = :query_id"
            ),
            {"query_id": entity_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_all(self, session: Session, *, limit: int = 100, offset: int = 0) -> list[Any]:
        rows = session.execute(
            text(
                "SELECT query_id, keywords, location_name, distance_from_location, "
                "status, last_scraped_at, last_error FROM ops.reed_search_queue "
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
                text("DELETE FROM ops.reed_search_queue WHERE query_id = :query_id"),
                {"query_id": entity},
            )

    def count(self, session: Session) -> int:
        return session.execute(text("SELECT count(*) FROM ops.reed_search_queue")).scalar() or 0

    # --- Queue-specific operations ---------------------------------------

    def seed_query(self, session: Session, search_query: ReedSearchQuery) -> None:
        """Insert a (keywords, location_name) combination if not already queued.

        distance_from_location is stored on first insert but is not part
        of the natural key -- re-seeding the same (keywords, location_name)
        pair with a different distance is a no-op (ON CONFLICT DO NOTHING),
        matching this table's documented "distance is override-only, not
        part of uniqueness" limitation (see the migration's own comment).
        """
        session.execute(
            text(
                "INSERT INTO ops.reed_search_queue "
                "(keywords, location_name, distance_from_location) "
                "VALUES (:keywords, :location_name, :distance_from_location) "
                "ON CONFLICT (keywords, location_name) DO NOTHING"
            ),
            {
                "keywords": _to_stored(search_query.keywords),
                "location_name": _to_stored(search_query.location_name),
                "distance_from_location": search_query.distance_from_location,
            },
        )

    def claim_next_queries(self, session: Session, limit: int) -> list[ClaimedReedQuery]:
        """Atomically claim up to `limit` due rows and mark them `in_progress`.

        Eligible: `pending` and `done` only (see the migration's column
        comment for why `done` stays eligible -- new UK postings appear
        against an already-searched combination over time). Oldest-due
        first (`last_scraped_at NULLS FIRST` -- never-attempted rows go
        first). `FOR UPDATE SKIP LOCKED` guards against two overlapping
        runs claiming the same row, same reasoning as
        ScrapeQueueRepository.claim_next_queries.

        Returns fewer than `limit` (including an empty list) if that many
        eligible rows don't exist -- never an error.
        """
        rows = session.execute(
            text(
                "WITH claimed AS ("
                "  SELECT query_id FROM ops.reed_search_queue "
                "  WHERE status IN ('pending', 'done') "
                "  ORDER BY last_scraped_at NULLS FIRST, query_id "
                "  LIMIT :limit "
                "  FOR UPDATE SKIP LOCKED"
                ") "
                "UPDATE ops.reed_search_queue q SET status = 'in_progress' "
                "FROM claimed c WHERE q.query_id = c.query_id "
                "RETURNING q.query_id, q.keywords, q.location_name, q.distance_from_location"
            ),
            {"limit": limit},
        ).all()
        return [
            ClaimedReedQuery(
                query_id=row.query_id,
                search_query=ReedSearchQuery(
                    keywords=_to_query_value(row.keywords),
                    location_name=_to_query_value(row.location_name),
                    distance_from_location=row.distance_from_location,
                ),
            )
            for row in rows
        ]

    def mark_query_result(
        self,
        session: Session,
        query_id: int,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        """Record how a claimed query's search ended.

        status must be one of 'done' (Search was fully paged, per
        ReedSettings.max_search_pages_per_query's cap or Reed's own
        totalResults being exhausted -- either way, this run's work on
        this query is complete) or 'failed' (the Search call itself
        raised a ReedError; see `error`). There is no 'pending' outcome
        here unlike Indeed's mark_query_result: Reed's own pagination
        never leaves a query genuinely half-finished the way a capped
        Selenium session can -- a claimed Reed query is always either
        fully searched or fails outright. Raises RepositoryError on an
        invalid status rather than letting a typo silently violate the
        table's own CHECK constraint with a less legible database error.
        """
        if status not in ("done", "failed"):
            raise RepositoryError(
                f"mark_query_result got status={status!r}; must be 'done' or 'failed'."
            )
        session.execute(
            text(
                "UPDATE ops.reed_search_queue SET "
                "status = :status, "
                "last_scraped_at = now(), "
                "last_error = :error "
                "WHERE query_id = :query_id"
            ),
            {"status": status, "error": error, "query_id": query_id},
        )

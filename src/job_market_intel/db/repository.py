"""
db.repository
==============

An abstract, generic repository base class that future table-specific
repositories (`CompanyRepository`, `JobRepository`, `SkillRepository`,
...) will inherit from.

Why a repository layer at all
-------------------------------
Without one, every scraper/service ends up writing its own ad hoc
`session.query(...)` calls scattered across the codebase, with no single
place to enforce "companies are always looked up by `domain` first, then
`normalized_name`" or "jobs are never hard-deleted." A repository gives
each entity exactly one place that knows how to persist and retrieve it,
which is what makes Step 23 (company dedup), Step 24 (skill extraction),
etc. maintainable once there are 15+ entities and 7+ scrapers all needing
to read/write them.

Scope of this step
--------------------
This file defines only the *shape* every repository will follow — a
`Generic[T]` abstract base with the CRUD operations every repository
needs, parameterized on session so repositories stay composable inside
whatever unit of work (`get_session()` / `transaction()`) the caller is
already in. It intentionally implements **no repository for any specific
table** — `CompanyRepository(AbstractRepository[Company])` etc. are
future work, once `models/` exists (see `db/base.py`).

Database-agnosticism
----------------------
The generic-typed, session-parameterized methods below don't reference
PostgreSQL-specific syntax anywhere; a subclass could target another
SQLAlchemy-supported backend without changing this contract. In practice
this project targets PostgreSQL exclusively (per the design doc), but
keeping the abstraction clean costs nothing and avoids quietly coupling
every future repository's *interface* to PostgreSQL-only concepts (only
individual repositories' *implementations* should do that, e.g. one using
`INSERT ... ON CONFLICT` for upserts).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from sqlalchemy.orm import Session

from job_market_intel.db.exceptions import RepositoryError

T = TypeVar("T")


class AbstractRepository(ABC, Generic[T]):
    """Base class for entity-specific repositories.

    Type parameter `T` is the ORM model type the repository manages
    (e.g. a future `Company` model). Every method takes the `Session`
    explicitly rather than owning one internally, so a repository call
    can participate in a caller's existing unit of work
    (`with get_session() as session: repo.add(session, obj)`) instead of
    silently opening a second, unrelated transaction.

    Subclasses must implement every abstract method below. Concrete
    subclasses belong in a future `repositories/` package (e.g.
    `repositories/company_repository.py`), one file per entity, mirroring
    the `models/` layout.
    """

    model: type[T]

    def __init__(self) -> None:
        if not hasattr(self, "model") or self.model is None:
            raise RepositoryError(
                f"{type(self).__name__} must set a `model` class attribute "
                "pointing at the ORM model it manages."
            )

    @abstractmethod
    def get_by_id(self, session: Session, entity_id: Any) -> T | None:
        """Returns the entity with the given primary key, or None."""
        raise NotImplementedError

    @abstractmethod
    def get_all(
        self, session: Session, *, limit: int = 100, offset: int = 0
    ) -> list[T]:
        """Returns a page of entities.

        `limit`/`offset` are required (with sane defaults) rather than
        optional-and-unbounded on purpose: this project's tables are
        expected to reach 100M+ rows (per the design doc), and an
        unbounded `get_all()` is exactly the kind of convenience method
        that quietly becomes an incident at scale if it's ever easy to
        call without thinking about pagination.
        """
        raise NotImplementedError

    @abstractmethod
    def add(self, session: Session, entity: T) -> T:
        """Stages a new entity for insertion (via `session.add`) and
        flushes so generated fields (e.g. identity PKs) are populated.
        Does not commit — committing is the caller's/unit-of-work's
        responsibility.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, session: Session, entity: T) -> T:
        """Persists changes to an already-tracked (or merged) entity.
        Does not commit.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, session: Session, entity: T) -> None:
        """Removes an entity.

        Concrete repositories for tables the design doc marks
        soft-delete-preferred (notably `core.jobs`, per Section 1.3 of
        the design doc: "Soft-delete rather than hard delete") should
        override this to update a status/`is_active` flag instead of
        issuing a real `DELETE`, and should document that override
        clearly since it changes the method's normal meaning.
        """
        raise NotImplementedError

    @abstractmethod
    def count(self, session: Session) -> int:
        """Returns the total number of rows for this entity.

        Provided as its own method (not `len(get_all(...))`) because at
        this project's target scale, counting must be a `SELECT count(*)`
        pushed to PostgreSQL, never a full fetch-then-len in Python.
        """
        raise NotImplementedError

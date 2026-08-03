"""
db.session
==========

Session creation and lifecycle management.

Design
------
A single module-level `sessionmaker` (`_session_factory`), bound to the
process-wide engine from `db.engine`, produces new `Session` objects on
demand. Sessions themselves are **never** module-level singletons — a
`Session` wraps one DB-API connection and is not safe to share across
threads or across unrelated units of work. The correct lifetime for a
`Session` is "one unit of work": one scrape-and-store operation, one API
request, one scheduled job run, one script invocation. This module's job
is to make creating and correctly tearing down that short-lived session
trivial for every caller, so nobody is tempted to hold one open longer
than that out of convenience.

Two entry points are provided:

- `get_session_factory()` — returns the raw `sessionmaker`, for callers
  that need finer control (e.g. a future FastAPI dependency that manages
  the session's lifecycle itself, tied to the request lifecycle).
- `get_session()` — a context manager wrapping the common case: open a
  session, yield it, commit on clean exit, roll back and re-raise as a
  `TransactionError` on failure, and always close the session
  afterward. This is what most callers (scrapers, seed scripts, one-off
  queries) should use.

Thread safety
-------------
`sessionmaker` itself is thread-safe to *call* (each call independently
produces a new `Session`); the `Session` instances it produces are not
thread-safe to share. Because `get_session()` hands each caller a
brand-new session scoped to a single `with` block, normal usage of this
module is thread-safe by construction — each thread/task gets its own
session. `scoped_session` is deliberately not used here: it optimizes for
"implicitly reuse the current thread's session," which is convenient in
simple single-threaded scripts but becomes a footgun the moment the
codebase adds async scraping, a thread pool, or a WSGI/ASGI server —
explicit session-per-unit-of-work avoids that trap from the start.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from job_market_intel.db.engine import get_engine
from job_market_intel.db.exceptions import TransactionError

_session_factory: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    """Returns the process-wide `sessionmaker`, creating it on first call.

    Configuration notes:

    - `expire_on_commit=False`: by default SQLAlchemy expires all ORM
      objects after commit, forcing a fresh SELECT the next time any
      attribute is touched. That's the right default for a typical web
      request but actively hostile to this project's workload (a
      scraper commits a batch, then immediately wants to read back
      inserted IDs / log a summary / hand objects to the next pipeline
      stage). Disabling it trades a small "attributes could technically
      be stale after commit" risk (irrelevant here — nothing else is
      concurrently mutating the same row within the same unit of work)
      for avoiding a wave of unnecessary post-commit SELECTs.
    - `autoflush=True` (default): keeps queries within a session
      consistent with pending changes without requiring callers to
      remember to flush manually.
    """
    global _session_factory

    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=True,
        )

    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager yielding a single-use `Session` scoped to one unit
    of work.

    Behavior:

    - On clean exit: commits.
    - On any exception: rolls back (guaranteeing the database is left in
      a consistent state — no partial writes survive), then re-raises as
      a `TransactionError` wrapping the original exception (preserved via
      `__cause__`).
    - Always: closes the session and returns its connection to the pool,
      regardless of outcome.

    Usage::

        from db.session import get_session
        from sqlalchemy import text

        with get_session() as session:
            session.execute(text("SELECT 1"))
            # commits automatically on clean exit

    For operations that need explicit transactional boundaries beyond
    "the whole block succeeds or fails together" (e.g. a savepoint around
    one risky insert inside a larger batch), see `db.transaction`.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as err:
        session.rollback()
        raise TransactionError(
            f"Transaction failed and was rolled back: {err}"
        ) from err
    except Exception:
        # Non-SQLAlchemy exceptions (e.g. a validation error raised by
        # calling code inside the `with` block) still must not leave a
        # half-committed transaction behind.
        session.rollback()
        raise
    finally:
        session.close()

"""
db.transaction
===============

Explicit transaction boundaries for cases `db.session.get_session()`'s
"whole block or nothing" behavior isn't granular enough for.

When to use this vs. plain `get_session()`
--------------------------------------------
Most callers just need `get_session()` — one unit of work, one commit,
one rollback on failure. Use `transaction()` *within* an existing session
when a smaller piece of a larger unit of work needs its own all-or-nothing
boundary without aborting everything around it. The canonical example
from this project: a scraper batch-inserting 500 job postings where row
#312 fails a constraint (e.g. a bad `content_hash`) — the other 499
should still commit. Wrapping each row's insert in `transaction(session)`
achieves that via a `SAVEPOINT`, without the caller having to construct
raw SQL.

Nested transactions
--------------------
SQLAlchemy implements "nested transactions" as SQL `SAVEPOINT`s
(`Session.begin_nested()`), which is the correct primitive here — true
nested *connections* aren't a PostgreSQL concept. A savepoint failure
rolls back only the work since that savepoint, leaving the outer
transaction still open and committable. This is genuinely useful for this
project's batch-ingestion workload (justifying the "if justified" caveat
in the requirements) and is implemented as an explicit opt-in, not the
default, because most callers don't need the added complexity.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from job_market_intel.db.exceptions import TransactionError


@contextmanager
def transaction(session: Session) -> Generator[Session, None, None]:
    """Wraps a block of work in its own transaction boundary on an
    already-open session.

    - If the session has no transaction in progress, begins one and
      commits/rolls back exactly like `get_session()` does (but does
      *not* close the session — that remains the caller's/outer context
      manager's responsibility).
    - If the session already has a transaction in progress (i.e. this is
      called from inside an outer `get_session()` block), begins a
      `SAVEPOINT` instead, so a failure here rolls back only this block's
      work, not the whole outer unit of work.

    Usage::

        with get_session() as session:
            for job in jobs:
                try:
                    with transaction(session):
                        session.add(job)
                except TransactionError:
                    log.warning("skipping bad row: %s", job)
            # session.commit() still runs on the outer get_session() exit,
            # committing every row that didn't fail its own savepoint.

    Raises
    ------
    TransactionError
        On failure, after rolling back. The session remains usable for
        further work afterward (this is the whole point of using a
        savepoint rather than letting the failure propagate to the outer
        transaction).
    """
    nested = session.in_transaction()
    begin = session.begin_nested if nested else session.begin

    try:
        with begin():
            yield session
    except SQLAlchemyError as err:
        raise TransactionError(
            f"Transaction block failed and was rolled back: {err}"
        ) from err

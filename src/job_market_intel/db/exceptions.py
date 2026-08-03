"""
db.exceptions
=============

Project-specific exceptions for the database layer.

Rationale
---------
SQLAlchemy's own exception hierarchy (`OperationalError`, `IntegrityError`,
`DisconnectionError`, ...) is precise but leaks driver/DB-API detail that
callers several layers up (a scraper, a FastAPI route handler, a Streamlit
callback) shouldn't need to know about. Wrapping low-level exceptions in a
small, intentional hierarchy gives every future caller exactly two things:

1. A stable set of exception types to catch, regardless of whether the
   underlying driver or database engine ever changes.
2. A clearer, actionable message, with the original exception preserved on
   `__cause__` (via `raise ... from err`) so nothing is silently lost for
   debugging.

Only the database layer should raise or catch raw SQLAlchemy exceptions.
Everything above it should catch these instead.
"""

from __future__ import annotations


class DatabaseError(Exception):
    """Base class for all errors raised by the `db` package.

    Catch this if a caller wants to handle "something went wrong talking
    to the database" generically, without caring which specific stage
    failed.
    """


class ConfigurationError(DatabaseError):
    """Raised when database configuration is missing, malformed, or
    otherwise cannot be used to establish a connection.

    Examples: missing `DATABASE_URL`, an unparsable pool-size value, a
    connection string missing a required component.
    """


class DatabaseConnectionError(DatabaseError):
    """Raised when the application cannot connect to, or loses, its
    connection to PostgreSQL.

    Wraps SQLAlchemy's `OperationalError` / `DisconnectionError` /
    `TimeoutError` family. Callers should generally treat this as
    retryable (see Step 12, Error Recovery) rather than fatal.
    """


class TransactionError(DatabaseError):
    """Raised when a transaction cannot be committed and has been rolled
    back.

    Wraps SQLAlchemy's `IntegrityError`, `PendingRollbackError`, and
    generic `SQLAlchemyError` cases encountered inside a transaction
    boundary. By the time this is raised, the session has already been
    rolled back — the database is guaranteed to be left in a consistent
    state.
    """


class RepositoryError(DatabaseError):
    """Raised by repository implementations for errors that are specific
    to a repository operation (e.g. a caller passed an entity type the
    repository doesn't manage) rather than a raw database failure.
    """

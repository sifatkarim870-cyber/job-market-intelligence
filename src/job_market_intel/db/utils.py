"""
db.utils
========

Small, generic, dependency-free-of-business-logic utility functions
built on top of `db.engine` / `db.session`.

These exist so that every future component that needs to answer "is the
database reachable?" (a Docker healthcheck endpoint, the monitoring
system in Step 33, a CLI preflight check, a pytest fixture) has one
shared, correct implementation to call instead of five slightly different
ad hoc `SELECT 1` snippets scattered across the codebase.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from job_market_intel.db.engine import dispose_engine, get_engine
from job_market_intel.db.exceptions import DatabaseConnectionError


def test_connection() -> bool:
    """Executes a trivial query to confirm the database is reachable.

    Returns
    -------
    bool
        True if the connection succeeded.

    Raises
    ------
    DatabaseConnectionError
        If the connection could not be established or the query failed.
        Callers that just want a boolean without exception handling
        should use `health_check()` instead.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as err:
        raise DatabaseConnectionError(
            f"Could not connect to the database: {err}"
        ) from err


def health_check() -> dict[str, Any]:
    """Returns a structured health-check result, never raising.

    Intended for use in monitoring/observability contexts (Step 33) and
    a future API `/health` endpoint, where a caller wants a status
    payload rather than an exception to catch.

    Returns
    -------
    dict
        ``{"healthy": bool, "latency_ms": float | None, "error": str | None}``
    """
    start = time.perf_counter()
    try:
        test_connection()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"healthy": True, "latency_ms": latency_ms, "error": None}
    except DatabaseConnectionError as err:
        return {"healthy": False, "latency_ms": None, "error": str(err)}


def dispose_all() -> None:
    """Disposes the engine's connection pool.

    Thin, explicit re-export of `db.engine.dispose_engine` kept here so
    callers doing general database housekeeping (test teardown,
    graceful-shutdown hooks) have one `db.utils` module to import from
    for connectivity/lifecycle utilities, without needing to know that
    disposal specifically lives in `engine.py`.
    """
    dispose_engine()

"""
Thin wrapper around the database interface built in Step 4.

This module calls get_engine() from db.engine to get the process-wide
SQLAlchemy engine.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection

# Import the get_engine function from your db package
from db.engine import get_engine


@contextmanager
def seed_connection() -> Iterator[Connection]:
    """
    Yields a single Connection wrapped in one transaction for the entire
    seed run. Commits on success, rolls back on any exception, and always
    closes the connection.
    """
    engine = get_engine()  # This creates the engine if it doesn't exist
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()
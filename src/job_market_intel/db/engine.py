"""
db.engine
=========

Owns the single SQLAlchemy `Engine` for the process.

Why a module-level singleton
-----------------------------
A SQLAlchemy `Engine` *is* a connection pool. Creating more than one per
process (per database) defeats pooling entirely — every additional engine
opens its own separate pool of physical connections, silently multiplying
load on PostgreSQL's `max_connections`. Every module in this codebase
(scrapers, seed scripts, the API, the dashboard) must call `get_engine()`
rather than constructing its own `create_engine(...)`, so that one process
== one pool, always.

The engine is created lazily on first use (not at import time) so that
importing `db` never has a side effect of opening a network connection —
useful for tests, tooling, and anything that imports the package without
immediately needing a live database.
"""

from __future__ import annotations

import threading

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import ArgumentError

from job_market_intel.db.config import DatabaseConfig, get_database_config
from job_market_intel.db.exceptions import ConfigurationError

_engine: Engine | None = None
_engine_lock = threading.Lock()


def get_engine(config: DatabaseConfig | None = None) -> Engine:
    """Returns the process-wide SQLAlchemy engine, creating it on first
    call.

    Parameters
    ----------
    config:
        Optional explicit configuration. Only used the *first* time the
        engine is created in this process — later calls (from other
        modules) get the same already-built engine regardless of what
        they pass. Pass this only from process entry points (e.g. a
        script's `main()` or a test fixture) that need non-default
        configuration; everyday callers should call `get_engine()` with
        no arguments.

    Pooling strategy
    -----------------
    Uses SQLAlchemy's default `QueuePool`, which is the right choice for
    this workload: a bounded number of long-lived worker processes
    (scrapers, API workers, scheduled jobs) each holding a small pool of
    reusable connections, versus e.g. `NullPool` (no pooling — wrong,
    reconnecting per query is far too slow for continuous scraping and
    high-frequency reads) or `StaticPool` (single shared connection —
    wrong, no concurrency).

    Raises
    ------
    ConfigurationError
        If configuration is missing/invalid, surfaced early and clearly
        rather than as an opaque failure on first query.
    """
    global _engine

    if _engine is not None:
        return _engine

    with _engine_lock:
        # Re-check after acquiring the lock: another thread may have
        # created the engine while this thread was waiting.
        if _engine is not None:
            return _engine

        cfg = config or get_database_config()

        try:
            _engine = create_engine(
                cfg.url,
                pool_size=cfg.pool_size,
                max_overflow=cfg.max_overflow,
                pool_timeout=cfg.pool_timeout,
                pool_recycle=cfg.pool_recycle,
                pool_pre_ping=cfg.pool_pre_ping,
                echo=cfg.echo,
                future=True,  # SQLAlchemy 2.x style execution semantics
                connect_args={"application_name": cfg.application_name},
            )
        except ArgumentError as err:
            raise ConfigurationError(
                f"Invalid database configuration: {err}"
            ) from err

        return _engine


def dispose_engine() -> None:
    """Disposes of the current engine's connection pool and clears the
    singleton.

    When to call this
    -------------------
    - In test teardown, to ensure each test session starts clean.
    - Before a process forks (e.g. a pre-fork worker manager) — pooled
      connections must never be shared across a fork, since the child
      inherits open file descriptors that both processes would then
      write to independently, corrupting the connection's protocol
      state.
    - During graceful shutdown, to release connections back to
      PostgreSQL promptly rather than waiting for the OS to reclaim
      them.

    Safe to call even if no engine has been created yet.
    """
    global _engine

    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None

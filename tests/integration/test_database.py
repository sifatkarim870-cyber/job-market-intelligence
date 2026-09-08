"""
tests/test_database.py

Tests for the `db` package established in Step 4.

Scope
-----
These tests verify the *interface layer itself* — engine creation, session
lifecycle, transaction commit/rollback, health checks, and configuration
validation. They do not test any table/model, since none are defined yet.

Test database
--------------
Tests that need a real connection use `TEST_DATABASE_URL` if set (point
this at a disposable local/CI Postgres instance — never production) and
are skipped otherwise, so the suite still runs (partially) in
environments without a database available. Tests that only need to
observe engine/session *behavior* use SQLite in-memory instead of a real
Postgres server, since the behavior under test (pooling wiring, session
commit/rollback semantics, exception wrapping) is driver-independent
SQLAlchemy behavior, not PostgreSQL-specific SQL. Nothing here writes to
or modifies any production data — no test targets `DATABASE_URL` from the
application's own `.env`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from job_market_intel.db.config import DatabaseConfig, get_database_config
from job_market_intel.db.exceptions import ConfigurationError, TransactionError
from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction
from job_market_intel.db.utils import health_check

# TEST_DATABASE_URL, the requires_live_db marker's skip behavior, and the
# live_engine fixture used below are all centralized in
# tests/integration/conftest.py — see that file's module docstring for why.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine(monkeypatch):
    """Provides a fresh in-memory SQLite engine wired through `db.engine`,
    isolated per test via `dispose_engine()` in teardown.
    """
    from job_market_intel.db import engine as engine_module

    engine_module.dispose_engine()
    monkeypatch.setattr(engine_module, "_engine", None)

    # We don't connect through DatabaseConfig/get_engine for these tests;
    # instead we directly build a sqlite engine and monkeypatch it in, to
    # exercise session/transaction *behavior* without requiring a real
    # Postgres driver or a live server.
    from sqlalchemy import create_engine

    sqlite_eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    monkeypatch.setattr(engine_module, "_engine", sqlite_eng)

    from job_market_intel.db import session as session_module

    monkeypatch.setattr(session_module, "_session_factory", None)

    yield sqlite_eng

    engine_module.dispose_engine()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestDatabaseConfig:
    def test_valid_url_accepted(self):
        cfg = DatabaseConfig(url="postgresql+psycopg://user:pw@localhost:5432/db")
        assert cfg.url.startswith("postgresql")

    def test_empty_url_raises_configuration_error(self):
        with pytest.raises(ConfigurationError):
            DatabaseConfig(url="")

    def test_non_postgres_url_raises_configuration_error(self):
        with pytest.raises(ConfigurationError):
            DatabaseConfig(url="mysql://user:pw@localhost/db")

    def test_invalid_pool_size_raises_configuration_error(self):
        with pytest.raises(ConfigurationError):
            DatabaseConfig(url="postgresql://localhost/db", pool_size=0)

    def test_password_is_redacted_in_repr(self):
        cfg = DatabaseConfig(url="postgresql://user:supersecret@localhost:5432/db")
        assert "supersecret" not in repr(cfg)
        assert "***" in repr(cfg)

    def test_get_database_config_raises_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        for var in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ConfigurationError):
            get_database_config()

    def test_get_database_config_builds_url_from_parts(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_NAME", "job_market_intelligence")
        monkeypatch.setenv("DB_USER", "app_user")
        monkeypatch.setenv("DB_PASSWORD", "pw")
        cfg = get_database_config()
        assert "localhost" in cfg.url
        assert "job_market_intelligence" in cfg.url

    def test_invalid_pool_env_var_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_POOL_SIZE", "not-a-number")
        with pytest.raises(ConfigurationError):
            get_database_config()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TestEngine:
    def test_get_engine_returns_singleton(self, sqlite_engine):
        from job_market_intel.db.engine import get_engine

        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_dispose_engine_clears_singleton(self, sqlite_engine):
        from job_market_intel.db import engine as engine_module

        engine_module.dispose_engine()
        assert engine_module._engine is None

    def test_engine_creation_fails_with_bad_config(self, monkeypatch):
        from job_market_intel.db import engine as engine_module

        engine_module.dispose_engine()
        monkeypatch.setattr(engine_module, "_engine", None)

        with pytest.raises(ConfigurationError):
            engine_module.get_engine(
                config=DatabaseConfig(url="postgresql://localhost/db", pool_size=-1)
            )


# ---------------------------------------------------------------------------
# Session lifecycle & transactions
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_session_commits_on_clean_exit(self, sqlite_engine):
        with get_session() as session:
            session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
            session.execute(text("INSERT INTO t (id) VALUES (1)"))

        with get_session() as session:
            result = session.execute(text("SELECT count(*) FROM t")).scalar()
            assert result == 1

    def test_session_rolls_back_on_exception(self, sqlite_engine):
        with get_session() as session:
            session.execute(text("CREATE TABLE t2 (id INTEGER PRIMARY KEY)"))

        with pytest.raises(TransactionError):
            with get_session() as session:
                session.execute(text("INSERT INTO t2 (id) VALUES (1)"))
                # Duplicate PK triggers an IntegrityError -> wrapped as
                # TransactionError, and the whole block should roll back.
                session.execute(text("INSERT INTO t2 (id) VALUES (1)"))

        with get_session() as session:
            result = session.execute(text("SELECT count(*) FROM t2")).scalar()
            assert result == 0

    def test_session_is_closed_after_context_exits(self, sqlite_engine):
        with get_session() as session:
            captured = session
        # After exit, the session should no longer have an active
        # transaction/connection bound to it.
        assert not captured.is_active or captured.get_transaction() is None

    def test_non_sqlalchemy_exception_still_rolls_back(self, sqlite_engine):
        with get_session() as session:
            session.execute(text("CREATE TABLE t3 (id INTEGER PRIMARY KEY)"))

        with pytest.raises(ValueError):
            with get_session() as session:
                session.execute(text("INSERT INTO t3 (id) VALUES (1)"))
                raise ValueError("business-logic error unrelated to SQL")

        with get_session() as session:
            result = session.execute(text("SELECT count(*) FROM t3")).scalar()
            assert result == 0


class TestTransactionSavepoints:
    def test_savepoint_rolls_back_independently_of_outer_transaction(
        self, sqlite_engine
    ):
        with get_session() as session:
            session.execute(text("CREATE TABLE t4 (id INTEGER PRIMARY KEY)"))
            session.execute(text("INSERT INTO t4 (id) VALUES (1)"))

            with pytest.raises(TransactionError):
                with transaction(session):
                    session.execute(text("INSERT INTO t4 (id) VALUES (1)"))  # dup PK

            # Outer transaction is still usable after the savepoint failure.
            session.execute(text("INSERT INTO t4 (id) VALUES (2)"))

        with get_session() as session:
            ids = session.execute(text("SELECT id FROM t4 ORDER BY id")).scalars().all()
            assert ids == [1, 2]


# ---------------------------------------------------------------------------
# Health check / connectivity
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_reports_healthy_for_working_engine(self, sqlite_engine):
        result = health_check()
        assert result["healthy"] is True
        assert result["error"] is None
        assert isinstance(result["latency_ms"], float)

    def test_health_check_reports_unhealthy_for_broken_engine(self, monkeypatch):
        from sqlalchemy import create_engine

        from job_market_intel.db import engine as engine_module

        engine_module.dispose_engine()
        # Point sqlite at a directory that cannot exist, forcing a
        # connection-time OperationalError. Using sqlite (always available,
        # no external driver required) rather than a fake Postgres DSN keeps
        # this test independent of whether psycopg happens to be installed
        # in the environment running the suite.
        broken = create_engine(
            "sqlite+pysqlite:////nonexistent/path/does/not/exist.db",
            future=True,
        )
        monkeypatch.setattr(engine_module, "_engine", broken)

        result = health_check()
        assert result["healthy"] is False
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# Live PostgreSQL integration tests (opt-in via TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


class TestLivePostgres:
    @pytest.mark.requires_live_db
    def test_connection_to_real_postgres_succeeds(self, live_engine):
        with live_engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1

    @pytest.mark.requires_live_db
    def test_health_check_against_real_postgres(self, live_engine):
        result = health_check()
        assert result["healthy"] is True

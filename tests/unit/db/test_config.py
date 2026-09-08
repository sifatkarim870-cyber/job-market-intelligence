"""tests/unit/db/test_config.py

Unit-level coverage for `job_market_intel.db.config`, added in Step 15.

Previously this module (68 statements) was only exercised indirectly by
`tests/integration/test_database.py::TestDatabaseConfig` — real tests,
but ones that don't need a live database and were sitting in the
"integration" folder as unit-speed coverage in disguise. This file adds
fast, isolated, unit-level coverage focused specifically on what Step 15
touched: the DB_POOL_MAX_OVERFLOW fix, and every pool-tuning variable's
parsing/validation path.

`tests/integration/test_database.py` still owns the engine-wiring and
live-Postgres-opt-in tests; nothing here duplicates those.
"""

from __future__ import annotations

import pytest

from job_market_intel.db.config import DatabaseConfig, get_database_config
from job_market_intel.db.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _clean_db_env(monkeypatch):
    """Every test in this file starts with a blank slate: none of the
    DB_* / DATABASE_URL variables leaking in from the real environment or
    a loaded .env file.
    """
    for var in (
        "DATABASE_URL",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_POOL_SIZE",
        "DB_POOL_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "DB_POOL_PRE_PING",
        "DB_ECHO",
        "DB_APPLICATION_NAME",
    ):
        monkeypatch.delenv(var, raising=False)


class TestDatabaseConfigConstruction:
    def test_valid_url_accepted(self):
        cfg = DatabaseConfig(url="postgresql+psycopg://user:pw@localhost:5432/db")
        assert cfg.url.startswith("postgresql")

    def test_empty_url_raises(self):
        with pytest.raises(ConfigurationError, match="url is empty"):
            DatabaseConfig(url="")

    def test_non_postgres_scheme_raises(self):
        with pytest.raises(ConfigurationError, match="PostgreSQL DSN"):
            DatabaseConfig(url="mysql://user:pw@localhost/db")

    @pytest.mark.parametrize(
        ("field", "value", "match"),
        [
            ("pool_size", 0, "pool_size must be >= 1"),
            ("max_overflow", -1, "max_overflow must be >= 0"),
            ("pool_timeout", 0, "pool_timeout must be >= 1"),
            ("pool_recycle", 0, "pool_recycle must be >= 1"),
        ],
    )
    def test_invalid_pool_field_raises(self, field, value, match):
        with pytest.raises(ConfigurationError, match=match):
            DatabaseConfig(url="postgresql://localhost/db", **{field: value})

    def test_defaults_match_documented_values(self):
        cfg = DatabaseConfig(url="postgresql://localhost/db")
        assert cfg.pool_size == 10
        assert cfg.max_overflow == 10
        assert cfg.pool_timeout == 30
        assert cfg.pool_recycle == 1800
        assert cfg.pool_pre_ping is True
        assert cfg.echo is False
        assert cfg.application_name == "job_market_intelligence"

    def test_password_redacted_in_repr(self):
        cfg = DatabaseConfig(url="postgresql://user:supersecret@localhost:5432/db")
        assert "supersecret" not in repr(cfg)
        assert "***" in repr(cfg)

    def test_url_without_credentials_reprs_unchanged(self):
        cfg = DatabaseConfig(url="postgresql://localhost:5432/db")
        assert "postgresql://localhost:5432/db" in repr(cfg)


class TestGetDatabaseConfigFromEnv:
    def test_raises_when_nothing_set(self):
        with pytest.raises(ConfigurationError, match="No database configuration found"):
            get_database_config()

    def test_uses_database_url_when_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/job_market_intelligence")
        cfg = get_database_config()
        assert cfg.url == "postgresql://localhost/job_market_intelligence"

    def test_builds_url_from_parts_when_database_url_absent(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_NAME", "job_market_intelligence")
        monkeypatch.setenv("DB_USER", "app_user")
        monkeypatch.setenv("DB_PASSWORD", "pw")
        cfg = get_database_config()
        assert "localhost" in cfg.url
        assert "job_market_intelligence" in cfg.url
        assert "app_user" in cfg.url

    def test_database_url_takes_precedence_over_parts(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://from-url/db")
        monkeypatch.setenv("DB_HOST", "from-parts")
        monkeypatch.setenv("DB_NAME", "job_market_intelligence")
        monkeypatch.setenv("DB_USER", "app_user")
        cfg = get_database_config()
        assert "from-url" in cfg.url
        assert "from-parts" not in cfg.url

    def test_incomplete_parts_do_not_build_a_url(self, monkeypatch):
        # DB_USER missing -> _build_url_from_parts() should bail out, not
        # produce a partially-built DSN.
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_NAME", "job_market_intelligence")
        with pytest.raises(ConfigurationError):
            get_database_config()

    def test_special_characters_in_password_are_url_encoded(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_NAME", "db")
        monkeypatch.setenv("DB_USER", "app_user")
        monkeypatch.setenv("DB_PASSWORD", "p@ss/word?")
        cfg = get_database_config()
        assert "p@ss/word?" not in cfg.url  # raw special chars must be encoded
        assert "%40" in cfg.url  # '@' encoded

    # --- Pool-tuning variables --------------------------------------------

    def test_db_pool_max_overflow_env_var_is_actually_read(self, monkeypatch):
        """The Step 15 fix, tested directly: setting the *documented*
        variable name must change the resulting config. Before the fix,
        this would have silently stayed at the default (10).
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_POOL_MAX_OVERFLOW", "25")
        cfg = get_database_config()
        assert cfg.max_overflow == 25

    def test_old_buggy_var_name_no_longer_has_any_effect(self, monkeypatch):
        """The old (wrong) name must be fully inert now — proves the fix
        isn't accidentally reading both names.
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_MAX_OVERFLOW", "999")
        cfg = get_database_config()
        assert cfg.max_overflow == 10  # default, unaffected by the old name

    def test_all_pool_tuning_vars_are_read(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_POOL_SIZE", "20")
        monkeypatch.setenv("DB_POOL_MAX_OVERFLOW", "5")
        monkeypatch.setenv("DB_POOL_TIMEOUT", "45")
        monkeypatch.setenv("DB_POOL_RECYCLE", "900")
        monkeypatch.setenv("DB_POOL_PRE_PING", "false")
        monkeypatch.setenv("DB_ECHO", "true")
        monkeypatch.setenv("DB_APPLICATION_NAME", "custom_app")
        cfg = get_database_config()
        assert cfg.pool_size == 20
        assert cfg.max_overflow == 5
        assert cfg.pool_timeout == 45
        assert cfg.pool_recycle == 900
        assert cfg.pool_pre_ping is False
        assert cfg.echo is True
        assert cfg.application_name == "custom_app"

    @pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on"])
    def test_bool_env_var_truthy_values(self, monkeypatch, truthy):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_ECHO", truthy)
        assert get_database_config().echo is True

    @pytest.mark.parametrize("falsy", ["0", "false", "no", "off", "garbage"])
    def test_bool_env_var_falsy_and_unrecognized_values(self, monkeypatch, falsy):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_ECHO", falsy)
        assert get_database_config().echo is False

    def test_invalid_int_env_var_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_POOL_SIZE", "not-a-number")
        with pytest.raises(ConfigurationError, match="must be an integer"):
            get_database_config()

    def test_empty_string_int_env_var_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_POOL_SIZE", "")
        assert get_database_config().pool_size == 10

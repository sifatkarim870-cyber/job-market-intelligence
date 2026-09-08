"""tests/unit/common/test_config.py

Unit-level coverage for `job_market_intel.common.config`, added in Step
15. Previously this module had 0% test coverage.

Scope note: as of Step 15, this module owns only app-level settings
(app_env, log_level). Database configuration lives in `db.config` and is
tested in `tests/unit/db/test_config.py` — see both modules' docstrings
for why the split happened.
"""

from __future__ import annotations

import pytest

from job_market_intel.common.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestSettingsDefaults:
    def test_default_app_env(self):
        assert Settings().app_env == "development"

    def test_default_log_level(self):
        assert Settings().log_level == "INFO"

    def test_is_production_false_by_default(self):
        assert Settings().is_production() is False


class TestSettingsFromEnv:
    def test_app_env_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        assert Settings().app_env == "production"

    def test_is_production_true_when_app_env_is_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        assert Settings().is_production() is True

    def test_is_production_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "PRODUCTION")
        assert Settings().is_production() is True

    def test_log_level_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        assert Settings().log_level == "DEBUG"

    def test_log_level_normalized_to_uppercase(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        assert Settings().log_level == "DEBUG"

    @pytest.mark.parametrize(
        "level", ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    )
    def test_every_valid_log_level_accepted(self, monkeypatch, level):
        monkeypatch.setenv("LOG_LEVEL", level)
        assert Settings().log_level == level

    def test_invalid_log_level_raises(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
        with pytest.raises(Exception, match="not a valid log level"):
            Settings()

    def test_env_var_names_are_case_insensitive(self, monkeypatch):
        # model_config sets case_sensitive=False
        monkeypatch.setenv("app_env", "staging")
        assert Settings().app_env == "staging"


class TestGetSettings:
    def test_returns_settings_instance(self):
        assert isinstance(get_settings(), Settings)

    def test_is_cached(self):
        assert get_settings() is get_settings()

    def test_raises_system_exit_on_invalid_value(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
        with pytest.raises(SystemExit, match="Configuration error"):
            get_settings()

    def test_does_not_have_database_fields(self):
        """Regression guard: database config must not creep back onto
        Settings — it lives in db.config now (see Step 15 rationale in
        this module's docstring). Prevents the exact drift-prone
        duplication that motivated the split in the first place.
        """
        fields = set(Settings.model_fields)
        assert fields == {"app_env", "log_level"}

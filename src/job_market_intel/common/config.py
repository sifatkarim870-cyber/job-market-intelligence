"""
Base application configuration loader.

Scope (established Step 3 — Configure the Development Environment;
finalized Step 15 — Build Configuration System):
    - Load environment variables from the process environment / a local
      .env file.
    - Validate presence and basic type-correctness of app-level settings:
      deployment environment and root log level.
    - Fail fast, with a clear error message, if a value is malformed.

Explicitly OUT of scope here:
    - Database connection settings. These live in
      `job_market_intel.db.config` (`DatabaseConfig` /
      `get_database_config()`), which is what `db.engine.get_engine()`
      actually calls to build the real, live SQLAlchemy engine. A
      `database_url` / `db_pool_size` / `db_pool_max_overflow` field set
      used to live on `Settings` here too, as a placeholder for an
      eventual "centralize everything" pass — but nothing outside this
      file ever read it, and it had already drifted out of sync with
      `db.config`'s real defaults (pool size 5 here vs. 10 there). Step 15
      removed the duplicate rather than reconciling it: one source of
      truth for DB config, not two that can silently disagree.
    - Scraper-specific settings (per-source URLs, delays, concurrency) —
      each scraper owns its own `*Settings` class (see
      `scrapers.remoteok.config.RemoteOKSettings`), following the same
      pydantic-settings + `env_prefix` pattern as this file.
    - Scheduler intervals — see `scheduler.config.SchedulerSettings`.
    - Feature flags — not yet needed; add a field here if/when a real one
      shows up rather than a JSONB-style catch-all.

Every environment variable this module reads is listed in
`KNOWN_ENV_VARS` below, checked against `.env.example` by
`tests/unit/test_config_env_consistency.py` — the Step 15 guard test that
exists because the database-config naming bug above (see `db.config`'s
docstring) went undetected for several steps.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_market_intel.common.logger import VALID_LOG_LEVELS

# Project root = three levels up from this file
# (src/job_market_intel/common/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"

KNOWN_ENV_VARS: tuple[str, ...] = ("APP_ENV", "LOG_LEVEL")
"""Every environment variable name this module reads, in one place — see
`db.config.KNOWN_ENV_VARS` for why this exists."""


class Settings(BaseSettings):
    """
    Minimal, validated application-level settings: deployment environment
    and root log level. Database configuration is deliberately not here —
    see `job_market_intel.db.config` instead.

    Values are read from (in order of precedence): real environment
    variables, then a `.env` file at the project root, then the defaults
    declared below.
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(
        default="development",
        description="Deployment environment: development | staging | production.",
    )
    log_level: str = Field(
        default="INFO",
        description="Root log level: DEBUG | INFO | WARNING | ERROR | CRITICAL.",
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Validates against the same VALID_LOG_LEVELS set that
        `common.logger.configure_logging()` itself enforces, rather than
        maintaining a second, independently-drifting list of valid
        levels. Normalizes to uppercase so `LOG_LEVEL=debug` in `.env`
        works exactly like `LOG_LEVEL=DEBUG`.
        """
        normalized = value.upper()
        if normalized not in VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level={value!r} is not a valid log level. "
                f"Choose one of: {sorted(VALID_LOG_LEVELS)}."
            )
        return normalized

    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached, validated Settings instance.

    Raises
    ------
    SystemExit
        If a value is invalid (currently: an unrecognized log_level) —
        fail fast at startup rather than surfacing a confusing error
        deep inside logging setup later.
    """
    try:
        return Settings()  # values come from env/.env; no required fields remain
    except ValidationError as exc:
        raise SystemExit(
            "Configuration error — one or more environment variables are "
            "invalid.\n\n"
            f"{exc}\n\n"
            "Fix: check .env against .env.example, or export a corrected "
            "value in your shell."
        ) from exc


if __name__ == "__main__":
    # Manual sanity check: `uv run python -m job_market_intel.common.config`
    settings = get_settings()
    print("Configuration loaded successfully:")
    print(f"  app_env    = {settings.app_env}")
    print(f"  log_level  = {settings.log_level}")
    print()
    print("Database configuration is checked separately — run:")
    print("  uv run python -m job_market_intel.db.config")

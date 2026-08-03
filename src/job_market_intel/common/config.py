"""
Base configuration loader.

Scope (Step 3 — Configure the Development Environment):
    - Load environment variables from the process environment / a local
      .env file.
    - Validate presence and basic type-correctness of the small set of
      settings needed to bootstrap the project (DB connection, app
      environment, log level).
    - Fail fast, with a clear error message, if required settings are
      missing or malformed.

Explicitly OUT of scope here (deferred to Step 14 — Configuration
Management):
    - Scraper-specific settings (per-source URLs, delays, concurrency).
    - Scheduler intervals.
    - Feature flags.
    - Any setting introduced ad hoc while building Steps 5-13.

Step 14 will import and extend `Settings` below rather than replacing it,
so nothing here needs to be redesigned later — only grown.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = three levels up from this file
# (src/job_market_intel/common/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """
    Minimal, validated application settings.

    Values are read from (in order of precedence): real environment
    variables, then a `.env` file at the project root, then the
    defaults declared below.
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Step 14 will add fields; don't error on unknowns yet
    )

    # --- Application environment -------------------------------------------------
    app_env: str = Field(
        default="development",
        description="Deployment environment: development | staging | production.",
    )
    log_level: str = Field(
        default="INFO",
        description="Root log level: DEBUG | INFO | WARNING | ERROR | CRITICAL.",
    )

    # --- PostgreSQL ----------------------------------------------------------------
    database_url: PostgresDsn = Field(
        ...,
        description=(
            "Full PostgreSQL DSN, e.g. "
            "postgresql+psycopg://user:password@host:5432/job_market_intelligence"
        ),
    )
    db_pool_size: int = Field(
        default=5,
        ge=1,
        description="Base SQLAlchemy connection pool size (tuned further in Step 4).",
    )
    db_pool_max_overflow: int = Field(
        default=10,
        ge=0,
        description="Additional connections allowed beyond db_pool_size under load.",
    )

    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached, validated Settings instance.

    Raises
    ------
    SystemExit
        If required environment variables are missing or invalid, with a
        clear, actionable message — fail fast at startup rather than
        surfacing a confusing error deep in the database layer later.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # values come from env/.env
    except ValidationError as exc:
        raise SystemExit(
            "Configuration error — one or more required environment "
            "variables are missing or invalid.\n\n"
            f"{exc}\n\n"
            "Fix: copy .env.example to .env and fill in real values, or "
            "export the missing variables in your shell."
        ) from exc


if __name__ == "__main__":
    # Manual sanity check: `python -m job_market_intel.common.config`
    settings = get_settings()
    print("Configuration loaded successfully:")
    print(f"  app_env           = {settings.app_env}")
    print(f"  log_level         = {settings.log_level}")
    _hosts = settings.database_url.hosts()
    _host_info = _hosts[0] if _hosts else {}
    _db_name = str(settings.database_url).rsplit("/", 1)[-1]
    print(f"  database_url      = {_host_info.get('host')}:{_host_info.get('port')}/{_db_name}")
    print(f"  db_pool_size      = {settings.db_pool_size}")
    print(f"  db_pool_max_overflow = {settings.db_pool_max_overflow}")

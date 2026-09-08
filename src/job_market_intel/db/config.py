"""
db.config
=========

Reads database connection settings from the environment.

This module intentionally owns *only* the database-relevant slice of
configuration. Step 3 (Configure the Development Environment) established
the `.env` file and the project's base config-loading convention. Step 15
(Build Configuration System) confirmed this module — not
`common.config.Settings` — is the real, load-bearing source of truth for
database connection settings (it's what `db.engine.get_engine()` actually
calls), and removed the unused, drifting duplicate fields that had been
sitting in `common.config.Settings` since Step 3. Nothing outside `db/`
should read `DATABASE_URL` (or its component parts) directly from
`os.environ` — go through `get_database_config()` instead.

Supported configuration
------------------------
Either a single `DATABASE_URL` (a full SQLAlchemy/PostgreSQL DSN), or the
individual `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD`
components, from which a DSN is assembled. `DATABASE_URL` takes
precedence if both are present.

Pool-tuning environment variables are optional and fall back to
production-sane defaults explained inline below.

Every environment variable this module reads is listed in
``KNOWN_ENV_VARS`` below — kept in sync by
``tests/unit/test_config_env_consistency.py``, a guard test added in Step
15 after a real bug was found here: this function previously read
``DB_MAX_OVERFLOW`` while ``.env.example`` (correctly) documented
``DB_POOL_MAX_OVERFLOW``, so setting the documented variable silently did
nothing. Fixed below; the guard test exists so a mismatch like that fails
the test suite instead of failing silently in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote_plus

from job_market_intel.db.exceptions import ConfigurationError

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is a dev convenience, not a hard dependency; in
    # containerized/production environments, real environment variables
    # are injected directly and this import is unnecessary.
    pass


KNOWN_ENV_VARS: tuple[str, ...] = (
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
)
"""Every environment variable name this module reads, in one place.

This is the single source of truth the Step 15 guard test
(``tests/unit/test_config_env_consistency.py``) checks against
``.env.example`` — add a name here whenever you add a new
``_env_int``/``_env_bool``/``os.getenv`` call below, or the guard test
will not know to check it.
"""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as err:
        raise ConfigurationError(
            f"Environment variable {name!r} must be an integer, got {raw!r}."
        ) from err


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DatabaseConfig:
    """Immutable, validated database configuration.

    Attributes
    ----------
    url:
        Full SQLAlchemy connection string, e.g.
        ``postgresql+psycopg://user:pass@host:5432/job_market_intelligence``.
    pool_size:
        Number of persistent connections kept open in the pool. Default
        (10) is sized for a single application process (one scraper run,
        one API worker, etc.) doing moderate concurrent work — not a
        cluster-wide budget. Each process that imports this module gets
        its own pool of this size, so total connections across a
        multi-worker deployment is `pool_size * worker_count` and must
        stay under PostgreSQL's `max_connections`.
    max_overflow:
        Extra connections allowed beyond `pool_size` under burst load
        before callers start blocking. Kept modest (10) because overflow
        connections are opened/closed per-use rather than pooled, so a
        large value trades connection-storm risk for less blocking.
    pool_timeout:
        Seconds a caller waits for a pooled connection before raising
        `TimeoutError`. 30s is long enough to ride out a brief spike
        without masking a genuinely exhausted pool for minutes.
    pool_recycle:
        Seconds after which a pooled connection is discarded and
        recreated, regardless of use. Set to 1800 (30 min) to stay safely
        under typical managed-Postgres (RDS/Cloud SQL) idle-connection
        and load-balancer timeouts, which commonly sit around 5-60
        minutes — recycling proactively avoids handing out a connection
        the server or an intermediate proxy has already dropped.
    pool_pre_ping:
        When True, SQLAlchemy issues a lightweight `SELECT 1` before
        handing a pooled connection to a caller, transparently
        reconnecting if it's dead. This is the primary defense against
        "stale connection" errors in long-running processes (the
        scheduler, a dashboard server) and is cheap enough to always
        leave on.
    echo:
        When True, SQLAlchemy logs every SQL statement. Off by default;
        useful for local debugging only — never enable in production
        (it will flood logs and can leak parameter values).
    application_name:
        Sent to PostgreSQL and visible in `pg_stat_activity.application_name`,
        which makes it possible to tell "the scraper" apart from "the API"
        apart from "the dashboard" in server-side connection monitoring.
    """

    url: str
    pool_size: int = 10
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    pool_pre_ping: bool = True
    echo: bool = False
    application_name: str = "job_market_intelligence"

    def __post_init__(self) -> None:
        if not self.url:
            raise ConfigurationError(
                "DatabaseConfig.url is empty. Set DATABASE_URL, or "
                "DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, in the "
                "environment or .env file."
            )
        if not self.url.startswith(("postgresql://", "postgresql+")):
            raise ConfigurationError(
                "DatabaseConfig.url must be a PostgreSQL DSN "
                "(postgresql:// or postgresql+<driver>://). "
                f"Got: {self._redacted_url()}"
            )
        if self.pool_size < 1:
            raise ConfigurationError("pool_size must be >= 1.")
        if self.max_overflow < 0:
            raise ConfigurationError("max_overflow must be >= 0.")
        if self.pool_timeout < 1:
            raise ConfigurationError("pool_timeout must be >= 1 second.")
        if self.pool_recycle < 1:
            raise ConfigurationError("pool_recycle must be >= 1 second.")

    def _redacted_url(self) -> str:
        """Returns the DSN with any password masked, for safe logging."""
        if "@" not in self.url:
            return self.url
        scheme_and_creds, rest = self.url.split("@", 1)
        if ":" not in scheme_and_creds:
            return self.url
        scheme_and_user, _password = scheme_and_creds.rsplit(":", 1)
        return f"{scheme_and_user}:***@{rest}"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"DatabaseConfig(url={self._redacted_url()!r}, "
            f"pool_size={self.pool_size}, max_overflow={self.max_overflow}, "
            f"pool_timeout={self.pool_timeout}, pool_recycle={self.pool_recycle}, "
            f"pool_pre_ping={self.pool_pre_ping}, echo={self.echo})"
        )


def _build_url_from_parts() -> str | None:
    host = os.getenv("DB_HOST")
    name = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD", "")
    port = os.getenv("DB_PORT", "5432")

    if not (host and name and user):
        return None

    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{name}"
    )


def get_database_config() -> DatabaseConfig:
    """Builds a validated `DatabaseConfig` from the environment.

    Precedence: `DATABASE_URL` if set, otherwise assembled from
    `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`.

    Raises
    ------
    ConfigurationError
        If no usable connection information is present, or if a
        pool-tuning environment variable can't be parsed.
    """
    url = os.getenv("DATABASE_URL") or _build_url_from_parts()
    if not url:
        raise ConfigurationError(
            "No database configuration found. Set DATABASE_URL, or all of "
            "DB_HOST/DB_NAME/DB_USER (DB_PASSWORD/DB_PORT optional), as "
            "environment variables or in a .env file."
        )

    return DatabaseConfig(
        url=url,
        pool_size=_env_int("DB_POOL_SIZE", 10),
        # Step 15 fix: this previously read "DB_MAX_OVERFLOW", which did
        # not match .env.example's documented "DB_POOL_MAX_OVERFLOW" (and
        # didn't match the DB_POOL_* naming used by every sibling
        # pool-tuning variable below) — so setting the documented variable
        # silently had no effect. See KNOWN_ENV_VARS and the module
        # docstring above.
        max_overflow=_env_int("DB_POOL_MAX_OVERFLOW", 10),
        pool_timeout=_env_int("DB_POOL_TIMEOUT", 30),
        pool_recycle=_env_int("DB_POOL_RECYCLE", 1800),
        pool_pre_ping=_env_bool("DB_POOL_PRE_PING", True),
        echo=_env_bool("DB_ECHO", False),
        application_name=os.getenv("DB_APPLICATION_NAME", "job_market_intelligence"),
    )


if __name__ == "__main__":
    # Manual sanity check: `uv run python -m job_market_intel.db.config`
    # Safe to run/print — DatabaseConfig.__repr__ redacts the password.
    try:
        cfg = get_database_config()
    except ConfigurationError as exc:
        raise SystemExit(f"Database configuration error: {exc}") from exc
    print("Database configuration loaded successfully:")
    print(f"  {cfg!r}")

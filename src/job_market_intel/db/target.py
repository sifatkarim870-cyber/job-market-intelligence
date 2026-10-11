"""Resolve which database a run should use.

Precedence
----------
1. ``CI_DATABASE_URL`` -- the persistent, hosted database. This is the variable
   every workflow passes, so switching providers is a one-secret change and
   never a code change. See ``docs/ci_database.md`` for the current target and
   the sizing arithmetic.
2. ``DATABASE_URL`` -- whatever the caller already set.
3. The ephemeral CI service container, inside GitHub Actions.
4. None, so ``db.config`` can fall back to the ``DB_*`` component parts.

Why a resolver at all
---------------------
The DSN used to be hardcoded to ``secrets.DATABASE_URL``, which pointed at a
Neon project whose quota was exhausted. Every workflow then died at its first
write with "Your account or project has exceeded the quota" -- an error that
names no provider and no remedy, in a workflow whose name says nothing about
databases.

Routing every job through one resolver means the next provider change is a
secret edit, and a failure names the variable that was wrong.

Note that the exhausted Neon project is NOT evidence that Neon is unusable.
Neon Free requires no card, allows 100 projects, and meters compute PER
PROJECT -- so a new project in the same account starts with a fresh allowance.
The alternative considered in detail (an Oracle Always Free VM, 200 GB, no
card needed for the database itself but one required at signup) is documented
in ``scripts/provision_ci_database.sh``.
"""

from __future__ import annotations

import os
from urllib.parse import quote

#: Set to "0" to force the local database even when CI_DATABASE_URL is present.
#: Used by the unit tests so they never reach the network.
USE_REMOTE_ENV = "JMI_USE_REMOTE_DB"

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

#: The throwaway container a scrape job starts when no hosted database is
#: configured. Seeded from the HF state snapshot and discarded at job end.
CONTAINER_DSN = "postgresql+psycopg://postgres:postgres@localhost:5432/jmi_ci"


def is_container(dsn: str) -> bool:
    """True for the ephemeral CI service container."""
    return "localhost:5432/jmi_ci" in dsn or "127.0.0.1:5432/jmi_ci" in dsn


def describe(dsn: str) -> str:
    """A host-qualified label that is safe to put in a log.

    Credentials never reach the log: only the host and database name are shown,
    because a leaked DSN in a workflow log is a leaked password.
    """
    try:
        tail = dsn.rsplit("@", 1)[-1]
    except AttributeError:
        return "unknown"
    return tail.rstrip("/")


def _encode_credentials(dsn: str) -> str:
    """Percent-encode user/password in a DSN's authority section.

    A password containing ``@``, ``/`` or ``?`` silently corrupts a DSN passed
    through as-is: SQLAlchemy parses at the first ``@``, so the string
    authenticates as the wrong user against the wrong host. The Oracle
    provisioning script generates a base64 password, which routinely contains
    exactly those characters, so this is the normal case rather than an edge one.

    Parsing is done from the RIGHT, which is what RFC 3986 requires and what
    makes an unencoded ``@`` inside a password recoverable:

      * the authority ends at the LAST ``@`` before the path, so the split is
        ``rfind("@")`` -- splitting on the first ``@`` would leave the real host
        embedded in the "password" and encode it away;
      * the path starts at the first ``/`` AFTER that ``@``, so a ``/`` inside a
        password does not truncate the authority.

    Nothing is split on ``?``: a query string legitimately contains one, and it
    is left exactly as the caller wrote it.
    """
    scheme, sep, rest = dsn.partition("://")
    if not sep or "@" not in rest:
        return dsn

    at = rest.rfind("@")
    authority, path = rest[:at], rest[at + 1 :]

    slash = path.find("/")
    host, tail = (path[:slash], path[slash:]) if slash != -1 else (path, "")

    if ":" not in authority:
        return dsn
    user, _colon, password = authority.partition(":")
    if not password:
        return dsn

    return f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}@{host}{tail}"


def resolve_dsn() -> str | None:
    """The DSN this process should use, or None to fall back to DB_* parts.

    Returns None rather than a local default when nothing is configured, so the
    caller can still assemble a URL from DB_HOST/DB_USER/DB_PASSWORD -- those
    credentials still need percent-encoding, and _build_url_from_parts() is what
    does it.
    """
    if os.environ.get(USE_REMOTE_ENV) == "0":
        # Force local and nothing else. Reading DATABASE_URL here would defeat
        # the point: CI sets that variable to the hosted database, so a test
        # run that "disabled the remote" this way would still reach the network.
        return LOCAL_DSN

    hosted = os.environ.get("CI_DATABASE_URL")
    if hosted:
        return _encode_credentials(hosted)

    generic = os.environ.get("DATABASE_URL")
    if generic:
        return _encode_credentials(generic)

    if os.environ.get("CI_CONTAINER_DB") == "1" or _in_ci():
        return CONTAINER_DSN

    return None


def _in_ci() -> bool:
    """True when running inside GitHub Actions.

    Every workflow that declares a postgres service container gets one, so
    this fallback only ever applies where no hosted DSN was supplied AND the
    job has a container to fall back to. A blank value is treated as absent
    throughout, because GitHub renders an unset secret as "" rather than
    leaving the variable unset -- and an empty DSN reaches the driver as a
    connection attempt against localhost with no database name.
    """
    return os.environ.get("GITHUB_ACTIONS") == "true"

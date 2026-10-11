"""tests/unit/db/test_target.py

``db.target.resolve_dsn`` is the single place that decides which database a run
writes to. It replaced a DSN hardcoded to ``secrets.DATABASE_URL``, which pointed
at Neon; when Neon's quota was exhausted every workflow died at its first write
with "Your account or project has exceeded the quota" -- an error naming no
provider and no remedy, in a workflow whose name says nothing about databases.

Two properties are load-bearing and both are easy to break silently:

  * precedence -- CI_DATABASE_URL must win, or switching provider means editing
    code in several places again, which is what this whole change removed;
  * credential encoding -- the provisioning script generates a base64 password,
    and base64 routinely contains '@' and '/'. Passed through unencoded, that
    authenticates as the wrong user against the wrong host.
"""

from __future__ import annotations

import pytest

from job_market_intel.db.target import (
    CONTAINER_DSN,
    LOCAL_DSN,
    _encode_credentials,
    describe,
    is_container,
    resolve_dsn,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "CI_DATABASE_URL",
        "DATABASE_URL",
        "CI_CONTAINER_DB",
        "JMI_USE_REMOTE_DB",
        "GITHUB_ACTIONS",
    ):
        monkeypatch.delenv(name, raising=False)


class TestPrecedence:
    def test_ci_database_url_wins(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@other:5432/other")
        monkeypatch.setenv("CI_DATABASE_URL", "postgresql+psycopg://u:p@hosted:5432/jmi")
        assert "hosted:5432/jmi" in resolve_dsn()

    def test_database_url_used_when_no_ci_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@generic:5432/g")
        assert "generic:5432/g" in resolve_dsn()

    def test_container_is_the_fallback(self, monkeypatch):
        monkeypatch.setenv("CI_CONTAINER_DB", "1")
        assert resolve_dsn() == CONTAINER_DSN

    def test_empty_secret_does_not_shadow_the_container(self, monkeypatch):
        """GitHub renders an unset secret as "".

        Every workflow declares DATABASE_URL and CI_DATABASE_URL from
        secrets.CI_DATABASE_URL unconditionally, so before that secret exists
        both arrive as the empty string. With only "blank means absent" the
        resolver found no configuration and two scrapers died with

            No database configuration found. Set DATABASE_URL, or all of ...

        A GitHub Actions job always has the postgres service container, so
        falling back to it there is correct and keeps CI working before the
        hosted database is provisioned.
        """
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("DATABASE_URL", "")
        monkeypatch.setenv("CI_DATABASE_URL", "")
        assert resolve_dsn() == CONTAINER_DSN

    def test_empty_secret_outside_ci_still_returns_none(self, monkeypatch):
        """The GitHub fallback must not fire on a laptop with a blank .env."""
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("DATABASE_URL", "")
        monkeypatch.setenv("CI_DATABASE_URL", "")
        assert resolve_dsn() is None

    def test_a_real_hosted_secret_still_wins_over_the_container(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("DATABASE_URL", "")
        monkeypatch.setenv("CI_DATABASE_URL", "postgresql+psycopg://u:p@hosted:5432/jmi")
        assert "hosted:5432/jmi" in resolve_dsn()

    def test_nothing_configured_returns_none_not_a_silent_local(self, monkeypatch):
        """None lets db.config fall back to DB_* parts.

        Returning a local DSN here would short-circuit _build_url_from_parts(),
        so a DB_HOST/DB_USER/DB_PASSWORD-only setup -- including every test
        that sets those three -- would silently get the wrong database. That
        regression is real: it broke test_special_characters_in_password_are_url_encoded.
        """
        assert resolve_dsn() is None

    def test_tests_can_force_local(self, monkeypatch):
        monkeypatch.setenv("JMI_USE_REMOTE_DB", "0")
        # DATABASE_URL is set too, and must be IGNORED -- CI sets it to the
        # hosted database, so reading it here would defeat the purpose.
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@remote:5432/r")
        monkeypatch.setenv("CI_DATABASE_URL", "postgresql+psycopg://u:p@hosted:5432/h")
        assert resolve_dsn() == LOCAL_DSN


class TestCredentialEncoding:
    def test_password_with_at_sign_is_encoded(self):
        out = _encode_credentials("postgresql+psycopg://u:p@ss@host:5432/db")
        assert "%40" in out
        # Exactly one '@' survives: the one separating credentials from host.
        assert out.count("@") == 1

    def test_password_with_slash_is_encoded(self):
        out = _encode_credentials("postgresql+psycopg://u:ab/cd@host:5432/db")
        assert "%2F" in out
        assert out.endswith("@host:5432/db")

    def test_query_string_is_not_mangled(self):
        """A '?' after the path starts a query string and must stay literal."""
        out = _encode_credentials("postgresql+psycopg://u:p@host:5432/db?sslmode=require")
        assert out.endswith("/db?sslmode=require")
        assert "%3F" not in out

    def test_dsn_without_credentials_is_untouched(self):
        raw = "postgresql+psycopg://host:5432/db"
        assert _encode_credentials(raw) == raw

    def test_encoding_applies_through_the_resolver(self, monkeypatch):
        monkeypatch.setenv("CI_DATABASE_URL", "postgresql+psycopg://u:se/cret@host:5432/db")
        assert "%2F" in resolve_dsn()

    def test_generated_base64_passwords_round_trip(self):
        """The passwords provision_ci_database.sh actually produces.

        That script builds a base64 password with '+' and '/' stripped, so
        roughly one in eight contains '@' or '/'. A first implementation split
        the authority at the FIRST '@' and the path at the FIRST '/', which
        mangled both cases and turned the password into part of the hostname.
        This exercises the shape end-to-end through SQLAlchemy's own parser.
        """
        import base64
        import secrets

        from sqlalchemy.engine import make_url

        for i in range(200):
            pw = (
                base64.b64encode(secrets.token_bytes(24))
                .decode()
                .replace("+", "")
                .replace("/", "")
                .replace("=", "")[:28]
            )
            if i % 3 == 0:
                pw += "@x/y?z="  # every character the encoder must survive
            url = make_url(
                _encode_credentials(f"postgresql+psycopg://jmi:{pw}@203.0.113.9:5432/jmi_ci")
            )
            assert url.host == "203.0.113.9"
            assert url.database == "jmi_ci"
            assert url.username == "jmi"
            assert url.password == pw


class TestLoggingSafety:
    def test_describe_never_leaks_the_password(self):
        """A DSN in a workflow log is a leaked password."""
        label = describe("postgresql+psycopg://user:hunter2@host:5432/db")
        assert "hunter2" not in label
        assert label == "host:5432/db"

    def test_is_container_identifies_the_ephemeral_db(self):
        assert is_container(CONTAINER_DSN)
        assert not is_container("postgresql+psycopg://u:p@db.example.com:5432/jmi")

"""Integration tests for the identity-sequence resync in the state restore.

Why this file exists
--------------------
On careers24's first CI run (2026-10-16) 30 of 100 postings failed with
``duplicate key value violates unique constraint "locations_pkey"``, and the
job still reported success.

The cause is not in careers24. ``scripts/restore_state_snapshot.py`` has to
insert **explicit** ids so the snapshot's foreign keys keep lining up, and
Postgres does **not** advance an identity sequence when a row is inserted with
an explicit id. On a freshly created database the sequence therefore still
reads 1, so the first row any scraper generates collides with the row the
snapshot already loaded at id 1.

It stayed hidden for so long because most sources resolve their locations to
ids that already exist, so they never generate one. Careers24 is the first
source here that creates new reference rows during a CI run.

These tests use TEMP tables rather than a scratch schema because the test role
(``app_user``) has no CREATE privilege on the database -- so a ``jmi_seqtest``
schema would make every test in this file error at setup and prove nothing.
Temp tables behave identically for this purpose: same identity column, same
PK violation, same sequence semantics, and they vanish on disconnect.

Run with:
    uv run pytest tests/integration/test_restore_identity_sequence.py -v
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

pytestmark = pytest.mark.requires_live_db

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "restore_state_snapshot.py"


def _load_module():
    """Import the script by path; scripts/ is not an importable package."""
    spec = importlib.util.spec_from_file_location("_restore_state_snapshot", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _temp_schema(conn: Connection, table: str) -> str:
    """The session's real temp schema (pg_temp_N), not the pg_temp alias."""
    return conn.execute(
        text(
            "SELECT table_schema FROM information_schema.tables "
            "WHERE table_name = :t AND table_schema LIKE 'pg_temp%'"
        ),
        {"t": table},
    ).scalar_one()


def _last_value(conn: Connection, schema: str, table: str, column: str) -> int | None:
    return conn.execute(
        text("SELECT pg_sequence_last_value(pg_get_serial_sequence(:st, :c))"),
        {"st": f"{schema}.{table}", "c": column},
    ).scalar_one()


def _max_id(conn: Connection, table: str, column: str) -> int:
    return int(conn.execute(text(f"SELECT COALESCE(MAX({column}), 0) FROM {table}")).scalar_one())


@pytest.fixture()
def cities(conn: Connection):
    """A temp table shaped like ``ref.cities``: one identity, one plain column.

    Yields ``(table, schema, resync)`` so each test can drive the restore's
    own helpers rather than reimplementing them.
    """
    conn.execute(
        text(
            "CREATE TEMP TABLE cities ("
            "  city_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            "  country_id integer NOT NULL,"
            "  city_name  text NOT NULL)"
        )
    )
    schema = _temp_schema(conn, "cities")
    module = _load_module()
    # The restore relaxes GENERATED ALWAYS so explicit ids can be loaded.
    module._relax_identity_columns(conn, schema, "cities")
    # No teardown: the temp table is scoped to the connection and the fixture
    # rolls the transaction back anyway. Dropping it here would fail whenever a
    # test deliberately triggered a constraint violation, because that leaves
    # the transaction aborted and every later command is rejected.
    yield "cities", schema, module._resync_identity_sequences


def _load_ids(conn: Connection, table: str, ids: list[int]) -> None:
    """Insert rows the way the snapshot does: explicit id, no sequence use."""
    for i in ids:
        conn.execute(
            text(f"INSERT INTO {table} (city_id, country_id, city_name) VALUES (:i, 1, :n)"),
            {"i": i, "n": f"City {i}"},
        )


class TestIdentitySequenceResync:
    def test_explicit_insert_alone_leaves_the_sequence_behind(
        self, conn: Connection, cities
    ) -> None:
        """The bug, stated as a fact Postgres itself confirms.

        Without this, the tests below could be passing for some other reason.
        """
        table, schema, _ = cities
        _load_ids(conn, table, [1, 41])

        assert _max_id(conn, table, "city_id") == 41
        assert _last_value(conn, schema, table, "city_id") is None, (
            "Postgres is expected to leave the sequence unused after explicit "
            "inserts; if this ever becomes false the resync may be redundant"
        )

    def test_the_ci_failure_reproduces_without_the_resync(self, conn: Connection, cities) -> None:
        """A generated insert collides with a loaded id -- CI's exact error."""
        table, _, _ = cities
        _load_ids(conn, table, [1, 41])

        # A savepoint, because the expected violation aborts the transaction and
        # every later command on it would be rejected.
        with pytest.raises(Exception, match="duplicate key"):
            with conn.begin_nested():
                conn.execute(
                    text(f"INSERT INTO {table} (country_id, city_name) VALUES (1, 'Pretoria')")
                )

    def test_resync_advances_the_sequence_to_max(self, conn: Connection, cities) -> None:
        table, schema, resync = cities
        _load_ids(conn, table, [1, 41, 42])

        assert resync(conn, [(schema, table)]) == [f"{schema}.cities.city_id unused->42"]
        assert _last_value(conn, schema, table, "city_id") == 42

    def test_after_resync_the_next_generated_row_does_not_collide(
        self, conn: Connection, cities
    ) -> None:
        """The CI failure, fixed. This is the test that matters."""
        table, schema, resync = cities
        _load_ids(conn, table, [1, 41, 42])

        resync(conn, [(schema, table)])
        conn.execute(text(f"INSERT INTO {table} (country_id, city_name) VALUES (1, 'Pretoria')"))
        conn.execute(text(f"INSERT INTO {table} (country_id, city_name) VALUES (1, 'Durban')"))

        assert [
            r[0] for r in conn.execute(text(f"SELECT city_id FROM {table} ORDER BY city_id"))
        ] == [1, 41, 42, 43, 44]

    def test_resync_is_idempotent(self, conn: Connection, cities) -> None:
        """The restore may run more than once; a second call must be a no-op."""
        table, schema, resync = cities
        _load_ids(conn, table, [1, 41])

        assert len(resync(conn, [(schema, table)])) == 1
        assert resync(conn, [(schema, table)]) == []

    def test_an_already_ahead_sequence_is_left_alone(self, conn: Connection, cities) -> None:
        """A development database's sequence is often ahead of its ids.

        Rewinding it to max(id) would reissue ids that already exist, which is
        the opposite failure. The resync must only ever move a sequence forward.
        """
        table, schema, resync = cities
        _load_ids(conn, table, [1, 41])
        conn.execute(
            text("SELECT setval(pg_get_serial_sequence(:st, 'city_id'), 900, true)"),
            {"st": f"{schema}.{table}"},
        )

        assert resync(conn, [(schema, table)]) == []
        assert _last_value(conn, schema, table, "city_id") == 900

    def test_an_empty_table_is_skipped(self, conn: Connection, cities) -> None:
        """No rows means no max to move to; setval(0) would break the column."""
        table, schema, resync = cities
        assert resync(conn, [(schema, table)]) == []

    def test_non_identity_columns_are_ignored(self, conn: Connection, cities) -> None:
        """``country_id`` is NOT NULL with no identity; it must not be resynced."""
        table, schema, resync = cities
        _load_ids(conn, table, [41])

        resynced = resync(conn, [(schema, table)])
        assert len(resynced) == 1
        assert resynced[0].startswith(f"{schema}.cities.city_id")

    def test_several_identity_columns_are_all_resynced(self, conn: Connection) -> None:
        """Generic by construction: any identity column, not a list of four."""
        conn.execute(
            text(
                "CREATE TEMP TABLE two_ids ("
                "  a_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
                "  b_id integer GENERATED ALWAYS AS IDENTITY,"
                "  note text)"
            )
        )
        schema = _temp_schema(conn, "two_ids")
        module = _load_module()
        module._relax_identity_columns(conn, schema, "two_ids")
        conn.execute(text("INSERT INTO two_ids (a_id, b_id, note) VALUES (7, 9, 'x')"))

        resynced = module._resync_identity_sequences(conn, [(schema, "two_ids")])
        assert sorted(r.split(" ")[0].split(".")[-1] for r in resynced) == ["a_id", "b_id"]
        assert sorted(r.split(" ", 1)[1] for r in resynced) == ["unused->7", "unused->9"]

        conn.execute(text("INSERT INTO two_ids (note) VALUES ('next')"))
        conn.execute(text("INSERT INTO two_ids (note) VALUES ('next')"))
        ids = [r[0] for r in conn.execute(text("SELECT a_id FROM two_ids ORDER BY a_id"))]
        assert ids == [7, 8, 9]

    def test_a_table_with_no_identity_columns_is_a_no_op(self, conn: Connection) -> None:
        conn.execute(text("CREATE TEMP TABLE plain (note text)"))
        schema = _temp_schema(conn, "plain")
        module = _load_module()
        conn.execute(text("INSERT INTO plain (note) VALUES ('x')"))
        assert module._resync_identity_sequences(conn, [(schema, "plain")]) == []

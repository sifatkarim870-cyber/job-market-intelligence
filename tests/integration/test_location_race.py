"""Concurrency tests for get_or_create_location.

The bug this file exists for
----------------------------
The first CI run of USAJOBS lost one row in twenty::

    failed to persist USAJOBS job 26-CB-13082116-DH: Transaction block failed
    and was rolled back: (psycopg.errors.UniqueViolation) duplicate key value
    violates unique constraint "locations_pkey"

``ref.locations`` has ``uq_locations_combo UNIQUE (city_id, region_id,
country_id, remote_work_type_id)``, and ``get_or_create_location`` is a
check-then-insert. Two sessions that both find nothing both insert, and the
loser's row is lost. It never reproduced locally because a single sequential
writer cannot race itself.

How the race is provoked, and why it is done this way
-----------------------------------------------------
The window is between the function's **own** SELECT and its **own** INSERT.
Inserting the winner row from outside the function does not reach it: the
function re-runs its SELECT on entry, so an externally committed row is already
visible and the INSERT never happens.

That is not a guess -- it is what the first version of this file did, and it
**passed against the unfixed code**, which made it worthless. The
``_RacingSession`` below therefore injects the collision between the function's
two statements: the first ``execute`` returns normally, and only then does
another session commit the winner. The SELECT the function acted on genuinely
said "no row", the INSERT genuinely violates the constraint, and the recovery
path exercised is the real one. No mocking of the function under test.

Two properties are asserted, and the second is the easy one to get wrong:

  1. the loser adopts the winner's ``location_id`` and leaves no duplicate;
  2. the rollback is scoped to a SAVEPOINT, so the caller's enclosing work
     survives. A plain ``session.rollback()`` would satisfy "did it raise?"
     while quietly discarding the job row the pipeline was persisting -- losing
     two rows instead of none.

Requires a real database, and is marked ``requires_live_db`` so it runs against
``TEST_DATABASE_URL`` rather than the developer's own database. That placement is
load-bearing, not tidiness: an earlier version of this file sat in
``tests/unit/``, connected to the live dev database, and its fixture borrowed
reference rows from ``ref.cities``. The integration suite re-seeds those tables,
so the borrowed rows were gone by the time the test body ran and all five tests
failed on foreign keys -- while passing in isolation, which is the worst
possible combination. The suite's own isolation pattern, seeding and removing
its own rows inside the test database, is the one to follow.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_market_intel.db.transaction import transaction
from job_market_intel.normalization.geographic_resolution import get_or_create_location

pytestmark = pytest.mark.requires_live_db

#: Marks rows this file creates so teardown can find them. A raw_location_text
#: marker is used rather than a synthetic key because every part of the combo is
#: a real foreign key into seeded reference data -- an invented country_id fails
#: the FK long before it can say anything about the UNIQUE race.
MARK = "zz-race-probe"


@pytest.fixture
def engine(live_engine):
    """The live test-database engine from tests/integration/conftest.py.

    Function-scoped because ``live_engine`` is: declaring this module-scoped
    would be a ScopeMismatch. The cost is one extra engine per test, which is
    immaterial next to the isolation it buys.
    """
    return live_engine


def _insert(session: Session, combo: dict, raw: str) -> int:
    return session.execute(
        text(
            "INSERT INTO ref.locations "
            "(city_id, region_id, country_id, remote_work_type_id, "
            "raw_location_text, is_global_remote) "
            "VALUES (:city_id, :region_id, :country_id, :remote_work_type_id, "
            ":raw, false) RETURNING location_id"
        ),
        {**combo, "raw": raw},
    ).scalar_one()


def _count_combo(session: Session, combo: dict) -> int:
    return session.execute(
        text(
            "SELECT count(*) FROM ref.locations WHERE "
            "city_id IS NOT DISTINCT FROM :city_id AND "
            "region_id IS NOT DISTINCT FROM :region_id AND "
            "country_id IS NOT DISTINCT FROM :country_id AND "
            "remote_work_type_id = :remote_work_type_id"
        ),
        combo,
    ).scalar_one()


def _other_remote_work_type_ids(engine, exclude: int, n: int) -> list[int]:
    """``n`` real remote_work_type_ids other than ``exclude``.

    Real ids again, never literals: the seeded ids on the test database start in
    the hundreds, so a hardcoded 2 or 3 fails the foreign key.
    """
    with Session(engine) as s:
        ids = [
            int(r[0])
            for r in s.execute(
                text(
                    "SELECT remote_work_type_id FROM ref.remote_work_types "
                    "WHERE remote_work_type_id <> :x ORDER BY remote_work_type_id LIMIT :n"
                ),
                {"x": exclude, "n": n},
            )
        ]
    if len(ids) < n:
        pytest.skip("not enough ref.remote_work_types rows for this test")
    return ids


def _is_lookup_for(args: tuple, combo: dict) -> bool:
    """True when this statement is the location lookup for exactly ``combo``.

    Matches on the bound parameters rather than the SQL text, so it stays
    correct if the query is reformatted.
    """
    stmt = args[0] if args else None
    params = args[1] if len(args) > 1 else None
    # `stmt or ""` would evaluate a ClauseElement's truth value, which raises
    # "Boolean value of this clause is not defined". Test for None instead.
    sql = "" if stmt is None else str(stmt)
    if "SELECT location_id FROM ref.locations" not in sql:
        return False
    if "RETURNING" in sql or not isinstance(params, dict):
        return False
    keys = ("city_id", "region_id", "country_id", "remote_work_type_id")
    if not all(k in params for k in keys):
        return False
    return all(params[k] == combo[k] for k in keys)


def _purge(s: Session) -> None:
    s.execute(
        text("DELETE FROM ref.locations WHERE raw_location_text LIKE :p"),
        {"p": f"{MARK}%"},
    )


def _teardown(s: Session) -> None:
    """Remove everything this module created, children before parents.

    Only ``ref.locations`` and this module's own probe reference rows are
    touched. Nothing here creates jobs or location aliases, and the runtime role
    has no DELETE on ``core.location_aliases`` at all, so reaching for them
    would fail on privileges rather than on the data.
    """
    _purge(s)
    s.execute(text("DELETE FROM ref.cities WHERE city_name = 'Race Probe City'"))
    s.execute(text("DELETE FROM ref.regions WHERE region_name = 'Race Probe Region'"))
    s.execute(text("DELETE FROM ref.countries WHERE iso_code_2 = :i"), {"i": PROBE_ISO})
    s.commit()


#: Reserved marker for reference rows this module creates and destroys. Ids are
#: taken from the identity columns (all four are GENERATED ALWAYS AS IDENTITY),
#: so they are read back with RETURNING rather than supplied. Note that
#: information_schema.column_default reads NULL for an identity column, which
#: makes an identity column look exactly like a plain NOT NULL one -- checking
#: is_identity is the only reliable way to tell. Getting that wrong is what
#: produced an earlier "no sequence anywhere" conclusion here.
PROBE_ISO = "ZZ"


@pytest.fixture
def remote_work_type_id(engine) -> int:
    """A real ``ref.remote_work_types`` id, looked up rather than assumed.

    Never hardcode 1. On the test database the seeded rows carry ids in the
    hundreds (measured 2026-10-15: ``ref.remote_work_types`` spans 115..120
    while its identity sequence sits at 4680), because the seeder upserts on
    every integration-test run and each run advances the sequence without
    necessarily adding a row. An assumed id fails the foreign key outright.
    """
    with Session(engine) as s:
        rid = s.execute(text("SELECT min(remote_work_type_id) FROM ref.remote_work_types")).scalar()
    if rid is None:
        pytest.skip("ref.remote_work_types is empty in this database")
    return int(rid)


@pytest.fixture
def free_region(engine, remote_work_type_id):
    """A fully-populated (city, region, country, remote) combo with no location row.

    Creates its own country/region/city and removes them afterwards, so the test
    does not depend on the contents of the shared reference tables. An earlier
    version selected an existing seeded city, and the full suite then failed on
    foreign keys when that row was not there any more.

    Every component must be non-NULL, and that is the whole point:
    ``uq_locations_combo UNIQUE (city_id, region_id, country_id,
    remote_work_type_id)`` uses plain UNIQUE, and in PostgreSQL NULLs are
    distinct from each other under it. A combo containing a NULL therefore
    **never** violates the constraint -- the module docstring says so, and it is
    why de-duplication is done in application code with IS NOT DISTINCT FROM
    rather than relying on the database. Such a combo cannot test the
    constraint path at all; only an all-non-NULL one can.
    """
    with Session(engine) as s:
        _teardown(s)
        country_id = s.execute(
            text(
                "INSERT INTO ref.countries (iso_code_2, iso_code_3, country_name) "
                "VALUES (:i2, 'ZZZ', 'Race Probe Country') RETURNING country_id"
            ),
            {"i2": PROBE_ISO},
        ).scalar_one()
        region_id = s.execute(
            text(
                "INSERT INTO ref.regions (country_id, region_name) "
                "VALUES (:c, 'Race Probe Region') RETURNING region_id"
            ),
            {"c": country_id},
        ).scalar_one()
        city_id = s.execute(
            text(
                "INSERT INTO ref.cities (region_id, country_id, city_name) "
                "VALUES (:r, :c, 'Race Probe City') RETURNING city_id"
            ),
            {"r": region_id, "c": country_id},
        ).scalar_one()
        s.commit()

    combo = {
        "city_id": int(city_id),
        "region_id": int(region_id),
        "country_id": int(country_id),
        "remote_work_type_id": remote_work_type_id,
    }
    yield combo
    with Session(engine) as s:
        _teardown(s)


class _RacingSession(Session):
    """A session that provably loses the insert race, deterministically.

    Commits a competing row the moment the function's **lookup SELECT** for
    ``combo`` returns, so the SELECT the function acted on genuinely said "no
    row" and the INSERT that follows genuinely violates the constraint.

    Keying on the combo rather than a call number matters. The obvious "collide
    on the Nth execute" version fires at the wrong place -- every
    get_or_create_location call issues several statements, so the count lands on
    a SELECT belonging to a *different* call, the collision never happens, and
    the test passes no matter how the recovery is written. That mistake was made
    and caught here; the check that it is now genuine is that swapping the
    SAVEPOINT for a bare ``session.rollback()`` makes it fail.
    """

    def __init__(self, *args, combo: dict | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._combo = combo
        self._fired = False

    def execute(self, *args, **kwargs):  # type: ignore[override]
        result = super().execute(*args, **kwargs)
        if self._combo is not None and not self._fired and _is_lookup_for(args, self._combo):
            self._fired = True
            with Session(self.bind) as winner:
                _insert(winner, self._combo, f"{MARK}-concurrent-winner")
                winner.commit()
        return result


class TestExistingRowIsReused:
    def test_second_call_returns_the_first_id(self, engine, free_region):
        with Session(engine) as s:
            first = get_or_create_location(
                s, **free_region, raw_location_text=f"{MARK}-reuse", is_global_remote=False
            )
            s.commit()
        with Session(engine) as s:
            second = get_or_create_location(
                s, **free_region, raw_location_text=f"{MARK}-reuse", is_global_remote=False
            )
            s.commit()
        assert second == first


class TestInsertRace:
    def test_loser_reuses_the_winners_row_instead_of_raising(self, engine, free_region):
        loser = _RacingSession(engine, combo=free_region)
        try:
            loser.begin()
            got = get_or_create_location(
                loser, **free_region, raw_location_text=f"{MARK}-loser", is_global_remote=False
            )
            loser.commit()
            assert got is not None
        finally:
            loser.close()

    def test_no_duplicate_row_is_left_behind(self, engine, free_region):
        loser = _RacingSession(engine, combo=free_region)
        try:
            loser.begin()
            get_or_create_location(
                loser, **free_region, raw_location_text=f"{MARK}-dup", is_global_remote=False
            )
            loser.commit()
        finally:
            loser.close()
        with Session(engine) as s:
            assert _count_combo(s, free_region) == 1, (
                "the race must not leave a second copy of the same combo"
            )

    def test_rollback_is_scoped_to_a_savepoint_not_the_whole_transaction(self, engine, free_region):
        """The caller's own work must survive the loser's failed INSERT.

        The pipeline wraps each job row in ``transaction(session)`` -- a
        SAVEPOINT -- so a full ``session.rollback()`` inside
        get_or_create_location would discard that job row too. Asserts both the
        row written before the savepoint and the one written inside it survive.
        """
        # The collision is keyed on the combo, so it lands on the third
        # get_or_create_location call -- the one inside transaction(loser),
        # which is the only place a rollback can be observed.
        loser = _RacingSession(engine, combo=free_region)
        others = _other_remote_work_type_ids(
            engine, exclude=free_region["remote_work_type_id"], n=2
        )
        try:
            loser.begin()
            marker = get_or_create_location(
                loser,
                **{**free_region, "remote_work_type_id": others[0]},
                raw_location_text=f"{MARK}-marker",
                is_global_remote=False,
            )
            with transaction(loser):
                inside = get_or_create_location(
                    loser,
                    **{**free_region, "remote_work_type_id": others[1]},
                    raw_location_text=f"{MARK}-inside-savepoint",
                    is_global_remote=False,
                )
                collided = get_or_create_location(
                    loser,
                    **free_region,
                    raw_location_text=f"{MARK}-loser2",
                    is_global_remote=False,
                )
            loser.commit()

            assert collided is not None
            with Session(engine) as check:
                for label, loc_id in (("before the savepoint", marker), ("inside it", inside)):
                    assert (
                        check.execute(
                            text("SELECT count(*) FROM ref.locations WHERE location_id = :i"),
                            {"i": loc_id},
                        ).scalar_one()
                        == 1
                    ), f"row written {label} was lost"
        finally:
            loser.close()


class TestNullCombosAreNotProtectedByTheConstraint:
    """Documents why the application-level check cannot simply be dropped.

    A combo with a NULL never collides under plain UNIQUE, so two concurrent
    inserts both succeed and the corpus gets two rows for the same place. The
    IS NOT DISTINCT FROM lookup is what prevents that -- and it is precisely
    that lookup which has the race window this module tests.
    """

    def test_two_rows_for_a_null_combo_are_both_accepted(self, engine, remote_work_type_id):
        combo = {
            "city_id": None,
            "region_id": None,
            "country_id": None,
            "remote_work_type_id": remote_work_type_id,
        }
        with Session(engine) as s:
            s.execute(
                text("DELETE FROM ref.locations WHERE raw_location_text LIKE :p"),
                {"p": f"{MARK}-null%"},
            )
            s.commit()
            first = _insert(s, combo, f"{MARK}-null-1")
            second = _insert(s, combo, f"{MARK}-null-2")
            s.commit()
        assert first != second, (
            "uq_locations_combo does NOT prevent this: that is the reason "
            "get_or_create_location de-duplicates in application code"
        )
        with Session(engine) as s:
            assert _count_combo(s, combo) == 2
            s.execute(
                text("DELETE FROM ref.locations WHERE raw_location_text LIKE :p"),
                {"p": f"{MARK}-null%"},
            )
            s.commit()


class TestUnrelatedIntegrityError:
    def test_an_unrelated_failure_still_propagates(self, engine):
        """A failure that is NOT the combo must not be silently swallowed.

        When the post-failure re-read finds nothing, the IntegrityError was
        something else entirely -- a bad foreign key, say -- and swallowing it
        would turn a loud error into a missing row.
        """
        with Session(engine) as s:
            s.begin()
            with pytest.raises(IntegrityError):
                get_or_create_location(
                    s,
                    city_id=None,
                    region_id=None,
                    # 999999 has no row in ref.remote_work_types: an FK
                    # violation, not the combo UNIQUE.
                    country_id=None,
                    remote_work_type_id=999_999,
                    raw_location_text=f"{MARK}-fk",
                    is_global_remote=False,
                )
            s.rollback()

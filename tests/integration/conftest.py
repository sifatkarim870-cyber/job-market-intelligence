"""tests/integration/conftest.py

Centralizes everything that was previously copy-pasted, with small
divergences, across ``test_database.py``, ``test_seed.py``, and
``test_remoteok_pipeline.py``:

1. The live-Postgres opt-in mechanism (``TEST_DATABASE_URL`` /
   "skip if not set").
2. The one transactional-isolation mechanic every live-DB test relies on
   (open a connection, begin a transaction, roll it back on teardown).

Why a marker + collection hook, not a shared ``pytest.mark.skipif`` object
----------------------------------------------------------------------------
The three files previously each did::

    TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
    requires_live_db = pytest.mark.skipif(not TEST_DATABASE_URL, reason=...)

and imported/used ``requires_live_db`` locally. Centralizing that *object*
would mean every test file importing it from this conftest module directly
(``from tests.integration.conftest import requires_live_db``), which is a
known pytest footgun — conftest.py is auto-loaded by pytest's own
collection machinery, and manually importing it as a regular module too
can register it under two different module identities.

Registering ``requires_live_db`` as a real pytest marker (see the
``markers`` entry in ``pyproject.toml``) and skipping via
``pytest_collection_modifyitems`` avoids that entirely: test files just
write ``@pytest.mark.requires_live_db`` (or
``pytestmark = pytest.mark.requires_live_db`` for a whole module) with no
import from this file at all. This is the standard pytest idiom for
"skip a whole class of tests based on an environment condition" — see
the pytest docs on skip/xfail.

Why three DB fixtures (``live_engine``, ``conn``, ``db_session``) and not one
--------------------------------------------------------------------------------
They cover genuinely different needs, not accidental divergence:

- ``live_engine``: a real, connected engine with *no* transaction wrapper
  — for tests that verify engine/connectivity behavior itself (nothing is
  written, so there's nothing to roll back).
- ``conn``: a transactional, unseeded ``Connection`` — for
  ``test_seed.py``, which is testing the seed scripts themselves and must
  start from an empty (but real) schema.
- ``db_session``: a transactional ORM ``Session``, pre-seeded with the
  minimal reference data (currencies, sources) that job-repository /
  pipeline tests need foreign keys to already exist for.

What *was* duplicated three times, and is now centralized once, is the
rollback-per-test isolation mechanic itself: ``db_connection`` below.
``conn`` and ``db_session`` both build on it instead of each re-opening
their own connection/transaction.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from job_market_intel.db import engine as engine_module

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

_SKIP_REASON = (
    "TEST_DATABASE_URL not set; skipping tests that need a live, "
    "schema-applied PostgreSQL instance."
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-skip every test marked ``requires_live_db`` when
    ``TEST_DATABASE_URL`` isn't set, so the suite still runs (minus the
    live-DB subset) in environments without a database available —
    replicates the previous per-file ``skipif`` behavior exactly, just
    from one place.
    """
    if TEST_DATABASE_URL:
        return
    skip_live_db = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "requires_live_db" in item.keywords:
            item.add_marker(skip_live_db)


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_engine():
    """The real, configured SQLAlchemy engine pointed at
    ``TEST_DATABASE_URL``. No transaction wrapper — for tests exercising
    engine/connectivity behavior itself.
    """
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL or ""
    engine_module.dispose_engine()
    yield engine_module.get_engine()
    engine_module.dispose_engine()


@pytest.fixture()
def db_connection(live_engine) -> Iterator[Connection]:
    """The single canonical transactional-isolation fixture: one
    connection, one transaction per test, rolled back on teardown. Every
    other live-Postgres fixture in this file builds on this instead of
    re-implementing it.
    """
    connection = live_engine.connect()
    trans = connection.begin()
    yield connection
    trans.rollback()
    connection.close()


@pytest.fixture()
def conn(db_connection: Connection) -> Connection:
    """A bare, unseeded transactional connection. Named ``conn`` (matching
    every existing call site in ``test_seed.py``) — seed tests are testing
    the seeding logic itself, so must start from an empty schema, not one
    with reference data pre-populated.
    """
    return db_connection


@pytest.fixture()
def db_session(db_connection: Connection) -> Iterator[Session]:
    """An ORM ``Session`` over the same rolled-back connection as
    ``db_connection``, pre-seeded with the minimal reference data
    (currencies, sources) that job-repository / pipeline tests need
    foreign keys to already exist for.
    """
    from seed.currencies import seed_currencies
    from seed.sources import seed_sources

    seed_currencies(db_connection)
    seed_sources(db_connection)

    session = Session(bind=db_connection)
    yield session
    session.close()

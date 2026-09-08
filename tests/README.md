# Testing conventions

This file documents how the test suite is organized and the conventions
established in Step 16 (Build Testing Framework), so the next ~50
scrapers' worth of tests follow one pattern instead of each
reinventing it. It's a convention guide, not a full pytest tutorial.

## Layout

```
tests/
├── conftest.py                # root fixtures — see "Shared factories" below
├── fixtures/                  # static sample payloads (e.g. sample API responses)
├── unit/                      # fast, isolated, no DB/network
└── integration/
    ├── conftest.py            # live-DB marker + transactional fixtures
    ├── test_database.py       # engine/session/transaction behavior
    ├── test_seed.py           # seed.* scripts against a real schema
    └── test_remoteok_pipeline.py  # a source's repository + pipeline, end-to-end
```

Unit tests never touch a database or the network. Integration tests may
require a live, schema-applied PostgreSQL instance — see below.

## Running the suite

```
uv run pytest                              # everything; live-DB tests skip without TEST_DATABASE_URL
TEST_DATABASE_URL=postgresql://... uv run pytest   # everything, including live-DB tests
uv run pytest -m requires_live_db          # only the live-DB tests
uv run pytest -m "not requires_live_db"    # everything except them, explicitly
uv run pytest tests/unit                   # unit only, fast, no DB needed ever
```

## The live-DB opt-in: `@pytest.mark.requires_live_db`

Any test (or whole module, via `pytestmark = pytest.mark.requires_live_db`)
that needs a real PostgreSQL instance gets this marker. It's registered in
`pyproject.toml` and auto-skipped by a `pytest_collection_modifyitems` hook
in `tests/integration/conftest.py` whenever `TEST_DATABASE_URL` isn't set
— skipped, not failed, so the rest of the suite still runs in any
environment.

`TEST_DATABASE_URL` must point at a disposable, schema-applied database —
never at `DATABASE_URL` / production data. Nothing in this suite targets
production.

**Don't** define a new local `TEST_DATABASE_URL` / skip check in a test
file — use the marker. **Don't** import anything from
`tests/integration/conftest.py` directly; fixtures and the marker are
picked up automatically by pytest.

## DB fixtures (`tests/integration/conftest.py`)

Three fixtures, each for a different need — pick the narrowest one that
fits, don't reach for `db_session` by default:

| Fixture | What it gives you | Use it when |
|---|---|---|
| `live_engine` | A real, connected engine, no transaction | Testing engine/connectivity behavior itself |
| `conn` | A transactional, **unseeded** `Connection`, rolled back after the test | Testing something that populates its own tables (e.g. a `seed.*` script) |
| `db_session` | A transactional ORM `Session`, **pre-seeded** with currencies + sources | Testing anything that needs those FKs to already exist (repository/pipeline tests) |

All three roll back automatically — nothing written during a test
persists in `TEST_DATABASE_URL`. If you need a new kind of DB fixture for
a future source (e.g. one pre-seeded with more reference data), add it to
`tests/integration/conftest.py` alongside these, building on the
`db_connection` fixture rather than opening a new connection/transaction
by hand.

## Shared factories (`tests/conftest.py`)

Two factory fixtures, available in every test under both `tests/unit` and
`tests/integration` with no import:

- **`make_cleaned_job(**overrides)`** — builds a `CleanedJob`, the
  source-agnostic contract every scraper's cleaner must output. Defaults
  to a minimal-but-valid record; override whatever fields your test cares
  about.
- **`make_raw_remoteok_job(**overrides)`** — builds a `RawRemoteOKJob`,
  fully populated by default (title, company, location, salary,
  description, tags, date all present) so a "healthy job" needs zero
  overrides.

**For a new source**, add one `make_raw_<source>_job` fixture next to
`make_raw_remoteok_job` in `tests/conftest.py` — same shape, same
override-everything convention. Reuse `make_cleaned_job` as-is; it's
already source-agnostic.

**Layering a "realistic preset" on a shared factory**: when a test file
wants a consistently-shaped "typical" record across several tests (see
`_remoteok_style_job` in `test_remoteok_pipeline.py`), write a small local
function that calls the shared fixture with a richer default set, rather
than a second standalone factory:

```python
def _my_source_style_job(make_cleaned_job, source_job_id="1", **overrides):
    defaults = {"company_name": "Acme", "skills": ["python"], ...}
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, **defaults)
```

## Unit-testing DB-touching code without a live database

`db/job_repository.py`'s `save_cleaned_job` runs Postgres-specific SQL
(`now()`, schema-qualified tables like `core.jobs`) — that's not portable
to SQLite, so its branch logic (insert vs. update vs. unchanged) is
unit-tested with a **mocked `Session`** instead (see
`tests/unit/db/test_job_repository.py::TestSaveCleanedJobBranches`):
collaborator methods (`get_or_create_company`, `get_usd_currency_id`) are
monkeypatched to fixed return values, and `Session.execute` is faked to
branch on the SQL text of each statement (not call order, so the test
doesn't break if the internal call sequence shifts without a real
behavior change).

This proves the *decision logic* is correct. It does not prove the SQL is
valid against real PostgreSQL — that's what the `requires_live_db`
integration tests in `test_remoteok_pipeline.py` are for. Both are needed;
neither is redundant with the other.

**For a future source's repository code**: if it's plain Python logic,
unit-test it directly. If it's raw SQL, prefer the mocked-`Session`
pattern above over reaching for SQLite, unless you've first checked the
SQL doesn't use Postgres-only syntax or schema-qualified table names.

## Coverage

`uv run pytest` runs with `--cov=src/job_market_intel --cov-report=term-missing`
by default (see `pyproject.toml`). There's no enforced minimum-coverage
gate, and that's deliberate — coverage percentage is a signal to look at,
not a target to chase for its own sake.

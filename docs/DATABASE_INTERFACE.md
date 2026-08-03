# Database Interface Layer — Developer Guide

**Audience:** a new backend developer joining the Job Market Intelligence
Platform project, who needs to talk to PostgreSQL from a scraper, a seed
script, the future API, or the future dashboard.

**Golden rule:** never call `create_engine(...)`, `sessionmaker(...)`, or
open a raw `psycopg` connection anywhere outside the `db/` package.
Import from `db` instead. This is what keeps connection pooling, error
handling, and transaction discipline consistent as the number of callers
grows.

---

## 1. Architecture

```
db/
├── __init__.py       # public exports — import from here
├── config.py          # env-driven DatabaseConfig (the only place reading DATABASE_URL)
├── engine.py           # process-wide Engine singleton (the connection pool)
├── session.py            # sessionmaker + get_session() context manager
├── base.py                 # shared DeclarativeBase for future ORM models
├── transaction.py           # savepoint-based nested transaction helper
├── utils.py                  # test_connection(), health_check(), dispose_all()
├── exceptions.py               # ConfigurationError, DatabaseConnectionError,
│                                #   TransactionError, RepositoryError
└── repository.py                # AbstractRepository[T] base class
```

Each file has exactly one responsibility:

| File | Owns | Does NOT own |
|---|---|---|
| `config.py` | Reading/validating connection settings | Opening any connection |
| `engine.py` | The one `Engine` (pool) per process | Sessions, queries |
| `session.py` | Creating/committing/closing `Session`s | Table-specific queries |
| `base.py` | The shared `DeclarativeBase`/`MetaData` | Any actual table mapping |
| `transaction.py` | Savepoint-scoped sub-transactions | Session creation |
| `utils.py` | Connectivity/health checks | Business logic |
| `exceptions.py` | The error vocabulary the rest of the app catches | — |
| `repository.py` | The CRUD *contract* future repositories follow | Any specific table |

### Why this split

- **Engine lifecycle vs. session lifecycle are different problems.** An
  `Engine` is expensive to create and should exist once per process for
  the process's whole life. A `Session` is cheap and should exist for
  exactly one unit of work (one scrape batch, one API request, one
  script run) and then be thrown away. Conflating them — e.g. one global
  `Session` reused everywhere — is the single most common SQLAlchemy
  misuse, and splitting `engine.py` from `session.py` makes it structurally
  awkward to make that mistake.
- **Config is isolated from engine construction** so validation errors
  ("you forgot to set `DATABASE_URL`") surface with a clear message at
  startup, instead of as an opaque driver error the first time someone
  runs a query.
- **`base.py` ships empty on purpose.** Table mapping is a per-entity
  concern that belongs with whichever feature first needs that entity
  (Step 24 needs `Skill`, Step 23 needs `Company`, etc.), not bundled
  into the generic infrastructure step. What `base.py` *does* guarantee —
  one shared `MetaData`/naming convention — is exactly the part that
  breaks badly if it's duplicated later instead of centralized now.
- **`repository.py` defines a contract, not implementations,** for the
  same reason: it's infrastructure every future repository needs to
  agree on (session-passed-in, paginated `get_all`, soft-delete-aware
  `delete`), while the actual per-table logic is out of scope here.

---

## 2. Engine

```python
from db import get_engine

engine = get_engine()  # created once per process, reused after that
```

- Uses SQLAlchemy's default `QueuePool`.
- `pool_size=10`, `max_overflow=10` — a moderate per-process budget.
  **Total connections across a deployment = `pool_size × number of
  processes`,** and must stay under PostgreSQL's `max_connections`. If
  you're about to run many worker processes concurrently (e.g. several
  scraper processes plus several API workers), either lower `pool_size`
  per process or introduce PgBouncer (already flagged in the design doc
  at 100M-row scale) rather than just raising the number.
- `pool_pre_ping=True` — always issues a cheap liveness check before
  handing out a pooled connection. Leave this on; it's the main defense
  against "server closed the connection unexpectedly" errors in
  long-running processes.
- `pool_recycle=1800` — connections older than 30 minutes are recycled
  proactively, to stay ahead of managed-Postgres/load-balancer idle
  timeouts.
- Configure via environment variables (see `.env.example`), never by
  editing `engine.py`.

Call `dispose_engine()` in test teardown, before forking a process, or
during graceful shutdown. You will rarely need this in application code.

---

## 3. Sessions

**The pattern you'll use 95% of the time:**

```python
from db import get_session
from sqlalchemy import text

with get_session() as session:
    session.execute(text("INSERT INTO ..."))
    # commits automatically here if no exception was raised
# rolls back automatically (and raises TransactionError) if one was
```

Rules of thumb:

- **One `get_session()` block per unit of work.** Don't hold a session
  open across an HTTP request boundary, across a `time.sleep()`, or
  across a whole scraper run touching thousands of pages — scope it to
  one batch/operation.
- **Never share a session across threads.** Each thread/task should call
  `get_session()` itself.
- `expire_on_commit=False` is set deliberately, so objects you just
  wrote remain readable immediately after commit (useful for logging
  inserted IDs, or handing objects to the next pipeline stage) without
  triggering a surprise re-SELECT.

If you need a smaller all-or-nothing boundary *inside* a larger unit of
work (e.g. batch-inserting 500 rows where one bad row shouldn't abort the
other 499), use `transaction()`:

```python
from db import get_session, transaction
from db.exceptions import TransactionError

with get_session() as session:
    for job in jobs:
        try:
            with transaction(session):
                session.add(job)
        except TransactionError:
            logger.warning("skipping bad row")
    # everything that didn't fail its own savepoint still commits here
```

---

## 4. Declarative Base

`db.base.Base` is the shared `DeclarativeBase` every future ORM model
must subclass. It carries an explicit naming convention matching the
existing raw-SQL schema's style (`uq_`, `ck_`, `fk_`, `pk_`, `idx_`
prefixes), so that if Alembic autogeneration is introduced later, its
migrations read consistently with `job_market_intelligence_schema.sql`.

No models are defined yet. When a feature needs one, create it under a
new `models/` package (mirroring the DB's `core`/`ref`/`bridge`/...
schemas), e.g.:

```python
# models/ref.py
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base

class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = {"schema": "ref"}

    skill_id: Mapped[int] = mapped_column(primary_key=True)
    skill_name: Mapped[str]
    ...
```

---

## 5. Custom Exceptions

Catch these, not raw SQLAlchemy exceptions, everywhere outside `db/`:

| Exception | Raised when |
|---|---|
| `ConfigurationError` | Missing/invalid connection settings |
| `DatabaseConnectionError` | Can't connect / connection lost |
| `TransactionError` | A transaction failed and was rolled back |
| `RepositoryError` | A repository is misconfigured/misused |

All wrap the original SQLAlchemy exception via `raise ... from err`, so
`exc.__cause__` still has the low-level detail for debugging/logging.

---

## 6. Repository Foundation

`db.repository.AbstractRepository[T]` is the contract every future
per-table repository implements: `get_by_id`, `get_all` (paginated —
never unbounded, this project targets 100M+ row tables), `add`,
`update`, `delete`, `count`. Every method takes the `Session` explicitly
so repository calls compose inside whatever unit of work the caller is
already in, instead of secretly opening their own.

No concrete repository exists yet — the first one arrives with the first
ORM model.

---

## 7. Common Mistakes to Avoid

- ❌ Creating your own `create_engine(...)` in a script "just this once."
  → Always `from db import get_engine`.
- ❌ Keeping a `Session` alive for an entire long-running process.
  → Scope it with `get_session()` per unit of work.
- ❌ Catching `sqlalchemy.exc.*` outside `db/`.
  → Catch `db.exceptions.*` instead.
- ❌ Calling `get_all()` on a repository without a `limit`.
  → It's required for a reason; these tables will be huge.
- ❌ Hard-deleting `core.jobs` rows via a repository's `delete()`.
  → The schema is soft-delete-preferred for jobs; override `delete()`
    in `JobRepository` to flip `job_status` instead, and document why.

---

## 8. Future Extension Points

- **Async support:** if a future component (e.g. an async FastAPI app in
  Step 34) needs it, add `AsyncEngine`/`AsyncSession` variants alongside
  the sync ones rather than replacing them — scrapers and batch scripts
  are simpler sync.
- **Read replicas:** the design doc flags read replicas for
  analytics/dashboard traffic at 10M+ rows. When that arrives, `engine.py`
  is the only file that needs a second `get_engine(role="replica")`-style
  entry point; nothing above it should need to change.
- **Alembic migrations:** once `models/` exists, wire up Alembic against
  `Base.metadata` from `db.base`.

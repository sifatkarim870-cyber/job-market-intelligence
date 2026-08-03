"""
db.base
=======

The single shared `DeclarativeBase` that every future ORM model in the
project will subclass.

Why this exists as its own module
-----------------------------------
SQLAlchemy requires all mapped classes that participate in the same
relationships/foreign keys to share one `MetaData` registry. Defining
`Base` once here — rather than letting each future model module define
its own — guarantees that guarantee holds automatically, and gives every
future migration tool (Alembic) a single `Base.metadata` to autogenerate
against.

This module defines *no tables*. Table mapping is explicitly out of scope
for this step; it belongs to whichever step first needs to read/write a
specific entity (company, job, skill, ...) and should live in its own
`models/` package, e.g. `models/core.py`, `models/ref.py`, mirroring the
`core` / `ref` / `bridge` / ... PostgreSQL schemas from the design doc.

Naming convention
------------------
An explicit naming convention is set on `MetaData` so that every
constraint/index SQLAlchemy generates (via ORM-level `Column(...,
index=True)`, or via Alembic autogeneration later) gets a deterministic,
greppable name instead of a driver-assigned one like `jobs_company_id_fkey1`.
This matters because the actual schema in production was created by raw
DDL (see `job_market_intelligence_schema.sql`), which already names every
constraint explicitly (`uq_jobs_source_natural_key`, `ck_jobs_status`,
etc.) — this convention keeps any *future* ORM-generated DDL consistent
with that existing style, which matters the day this project introduces
Alembic and needs autogenerate diffs to be readable.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Mirrors the naming style already used throughout
# job_market_intelligence_schema.sql (uq_, ck_, idx_, fk_ prefixes).
NAMING_CONVENTION = {
    "ix": "idx_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base for all future ORM models.

    Usage (in a future `models/` module, not part of this step):

        from db.base import Base
        from sqlalchemy.orm import Mapped, mapped_column

        class Source(Base):
            __tablename__ = "sources"
            __table_args__ = {"schema": "ref"}

            source_id: Mapped[int] = mapped_column(primary_key=True)
            ...
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

"""
Shared idempotent upsert engine used by every individual seed module.

Design choice: idempotency keys off NATURAL/business keys (e.g. `iso_code`,
`code`, `normalized_skill_name`), never off the surrogate identity PK. This
means:
  - Re-running a seed never creates duplicate rows.
  - Re-running a seed with a corrected `label`/`description` self-heals the
    row via DO UPDATE, without ever changing the surrogate ID other tables
    already reference via FK.
  - If a row was manually edited in prod after seeding (e.g. a curator fixed
    a typo), re-seeding will overwrite that edit for the columns listed in
    `update_cols` — call out any table where that's undesirable and set
    `update_cols=[]` (insert-only, never update) instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import Connection, Table, MetaData, text
from sqlalchemy.dialects.postgresql import insert as pg_insert


@dataclass
class SeedResult:
    table: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged

    def __str__(self) -> str:
        status = "OK" if not self.errors else "ERRORS"
        return (
            f"[{status}] {self.table}: "
            f"{self.inserted} inserted, {self.updated} updated, "
            f"{self.unchanged} unchanged"
            + (f", {len(self.errors)} errors" if self.errors else "")
        )


def upsert_many(
    conn: Connection,
    *,
    schema: str,
    table_name: str,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
    update_cols: Sequence[str] | None = None,
) -> SeedResult:
    """
    Idempotent bulk upsert using PostgreSQL's native
    INSERT ... ON CONFLICT (...) DO UPDATE / DO NOTHING.

    `conflict_cols` must match an existing UNIQUE constraint or PK on the
    table (e.g. ('iso_code',) or ('country_id', 'region_name')).

    `update_cols=None` -> update every column present in `rows[0]` except
    the conflict columns (typical case: keep reference data fresh).
    `update_cols=[]`   -> DO NOTHING on conflict (insert-only; use for
                          tables where manual prod edits must never be
                          clobbered by re-seeding).
    """
    result = SeedResult(table=f"{schema}.{table_name}")
    if not rows:
        return result

    meta = MetaData(schema=schema)
    tbl = Table(table_name, meta, autoload_with=conn)

    cols = list(rows[0].keys())
    if update_cols is None:
        update_cols = [c for c in cols if c not in conflict_cols]

    stmt = pg_insert(tbl).values(list(rows))

    if update_cols:
        set_ = {c: getattr(stmt.excluded, c) for c in update_cols}
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_=set_,
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(conflict_cols))

    # RETURNING xmax = 0 is the standard PG trick to distinguish a fresh
    # INSERT (xmax=0) from an UPDATE-via-conflict (xmax<>0) in the same
    # statement, giving us accurate inserted/updated counts in one round-trip.
    stmt = stmt.returning(text("(xmax = 0) AS inserted"))

    try:
        rs = conn.execute(stmt)
        for row in rs:
            if row.inserted:
                result.inserted += 1
            else:
                result.updated += 1
        result.unchanged = len(rows) - result.inserted - result.updated
    except Exception as exc:  # noqa: BLE001
        result.errors.append(str(exc))
        raise

    return result


def get_id_map(
    conn: Connection, *, schema: str, table_name: str, key_col: str, id_col: str
) -> dict[Any, Any]:
    """
    Convenience helper: fetch {natural_key: surrogate_id} for a just-seeded
    table, used by downstream modules that need to resolve FKs (e.g.
    regions.py resolving country_id from an ISO code).
    """
    rows = conn.execute(
        text(f"SELECT {key_col}, {id_col} FROM {schema}.{table_name}")
    ).all()
    return {r[0]: r[1] for r in rows}
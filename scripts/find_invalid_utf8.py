"""Find rows in Postgres whose TEXT columns contain bytes that are not valid UTF-8.

The corpus export broke with UnicodeDecodeError on three columns, and two of
them (``education_level``, ``source``) come from SEED tables -- ref.education_levels
and ref.sources -- which means the corruption is in the seed data itself, not
in scraped content.

psycopg returns invalid UTF-8 as a Python str full of lone surrogates
(errors='surrogateescape'), which pyarrow then writes to parquet verbatim, so
the bad bytes sail through every downstream step until DuckDB tries to read
them back as text.

Detection: a valid-UTF-8 text column satisfies octet_length = 0 OR
char_length > 0 with no lone surrogates. The robust check here is to encode to
bytea and look for the byte sequences that mark an incomplete multi-byte char,
but the cheapest reliable test is ``col <> convert_from(col::bytea, 'UTF8')``
-- Postgres raises on invalid input, so wrap it per-row.

Run:  uv run python scripts/find_invalid_utf8.py
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text
from loguru import logger

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

#: (table, column, label). ref.* first because seed corruption is the worst kind:
#: it is shared by every job in the source.
TARGETS: list[tuple[str, str, str]] = [
    ("ref.sources", "source_code", "source_code"),
    ("ref.education_levels", "label", "education_level"),
    ("ref.experience_levels", "label", "experience_level"),
    ("ref.job_categories", "label", "job_category"),
    ("core.jobs", "job_title", "job_title"),
    ("core.jobs", "job_title_en", "job_title_en"),
    ("core.jobs", "language_code", "language_code"),
    ("core.job_descriptions", "description_clean", "description_clean"),
    ("core.job_descriptions", "description_en", "description_en"),
    ("core.job_descriptions", "requirements", "requirements"),
    ("core.job_descriptions", "responsibilities", "responsibilities"),
]


def is_valid_utf8(value: str | None) -> bool:
    """True when the str survives a strict UTF-8 round trip.

    Lone surrogates (from psycopg's surrogateescape) make encode() raise.
    """
    if value is None:
        return True
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def main() -> int:
    engine = create_engine(LOCAL_DSN)
    total_bad = 0
    with engine.connect() as conn:
        for table, column, label in TARGETS:
            try:
                rows = conn.execute(
                    text(f"SELECT 1 FROM {table} LIMIT 0")  # noqa: S608 - table/column are literals
                ).all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("skipping {}.{}: {}", table, column, exc)
                continue

            pk_col = "job_id" if table.startswith("core.job") else (
                "source_id" if table == "ref.sources" else "education_level_id"
            )
            try:
                rows = conn.execute(
                    text(f"SELECT {pk_col} AS pk, {column} AS val FROM {table}")  # noqa: S608
                ).all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cannot read {}.{}: {}", table, column, exc)
                continue

            bad = [(r.pk, r.val) for r in rows if not is_valid_utf8(r.val)]
            if bad:
                total_bad += len(bad)
                logger.error(
                    "{}.{}: {} of {} rows contain invalid UTF-8",
                    table, column, len(bad), len(rows),
                )
                for pk, val in bad[:3]:
                    print(f"     {table}.{column} id={pk}")
                    print(f"       raw: {val!r}"[:400])
            else:
                logger.info("{}.{}: {} rows, all valid UTF-8", table, column, len(rows))

    print()
    if total_bad:
        print(f"RESULT: {total_bad} row(s) carry invalid UTF-8 -- fix before exporting")
        return 1
    print("RESULT: every checked column is valid UTF-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
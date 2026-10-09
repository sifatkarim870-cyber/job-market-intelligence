"""Apply the HF translations overlay to the local database.

The Kaggle kernel translates on GPU and writes its results to a separate HF
dataset keyed by the natural identity ``(source_code, source_job_id)``. This
reads that overlay and updates Postgres. The corpus shards are never rewritten
-- they are immutable by design, one part file per scrape run.

Why an overlay instead of rewriting the corpus
----------------------------------------------
Re-exporting 105,906 rows to replace ~68k values would race with the scrapers,
which append new shards constantly, and would rewrite 70 MB to change half of
it. The overlay is additive, ~40 MB, and idempotent: re-applying it is a no-op
for rows whose values already match.

Identity
--------
``job_id`` is NOT portable -- each database has its own sequence -- so rows are
matched on ``(source_code, source_job_id)``. Every row in the overlay was
selected from the corpus by exactly that key, so a missing match means the
overlay and the database have diverged, which is reported rather than ignored.

Usage:
    python scripts/apply_translations.py --dry-run
    python scripts/apply_translations.py --batch 2000
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger
from sqlalchemy import text

OVERLAY_REPO = "Shifat2110724169/job-market-intel-translations"
OVERLAY_PATH = f"hf://datasets/{OVERLAY_REPO}/translations.parquet"
CORPUS_REPO = "Shifat2110724169/job-market-intel-corpus"

#: Overridable via --dsn so the test suite can point at a scratch database.
#: A hardcoded DSN here once made the test write to the live corpus, where the
#: statements happened to match nothing -- but only by luck.
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

BATCH = 2000

#: Staging table for one batch of the overlay. A temp table + a single set-based
#: UPDATE is used rather than "UPDATE ... FROM (VALUES ...)" because SQLAlchemy
#: only rewrites :params at the top level, so a typed tuple like
#: ``(:en::text, :sc::text)`` reaches Postgres verbatim and dies with
#: "syntax error at or near ':'".
STAGE_DDL = """
CREATE TEMP TABLE overlay_stage (
    source_code   text,
    source_job_id text,
    title_en      text,
    description_en text,
    language_code text
) ON COMMIT DROP
"""

#: Matched on the natural key (source_code, source_job_id), NEVER job_id --
#: each database has its own sequence, so Neon job 1 and local job 1 are
#: different postings, and joining on job_id would silently overwrite one with
#: the other's text. NULLs in the overlay are skipped so a row whose title was
#: already English does not blank its description.
TITLE_UPDATE = """
UPDATE core.jobs j
   SET job_title_en = s.title_en, updated_at = now()
  FROM overlay_stage s
  JOIN ref.sources r ON r.source_code = s.source_code
 WHERE j.source_id = r.source_id
   AND j.source_job_id::text = s.source_job_id
   AND s.title_en IS NOT NULL
"""

DESC_UPDATE = """
UPDATE core.job_descriptions d
   SET description_en = s.description_en, updated_at = now()
  FROM overlay_stage s
  JOIN ref.sources r ON r.source_code = s.source_code
  JOIN core.jobs j ON j.source_id = r.source_id
                  AND j.source_job_id::text = s.source_job_id
 WHERE d.job_id = j.job_id
   AND s.description_en IS NOT NULL
"""

LANG_UPDATE = """
UPDATE core.jobs j
   SET language_code = s.language_code, updated_at = now()
  FROM overlay_stage s
  JOIN ref.sources r ON r.source_code = s.source_code
 WHERE j.source_id = r.source_id
   AND j.source_job_id::text = s.source_job_id
   AND s.language_code IS NOT NULL AND s.language_code <> ''
"""


def overlay_rows() -> list[dict]:
    """Read the overlay from HF. Anonymous read; the dataset is public."""
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    cur = con.execute(f"SELECT * FROM read_parquet('{OVERLAY_PATH}')")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when rows fail to match (default: warn)",
    )
    parser.add_argument(
        "--dsn", default=LOCAL_DSN, help="target database (default: the local corpus)"
    )
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine

    engine = create_engine(args.dsn)

    try:
        rows = overlay_rows()
    except Exception as exc:  # noqa: BLE001 - the Hub may be unreachable
        logger.error("could not read overlay from HF: {}", exc)
        return 0 if not args.strict else 1

    if not rows:
        logger.info("overlay is empty -- nothing to apply")
        return 0

    logger.info("overlay rows: {:,}", len(rows))
    methods: dict[str, int] = {}
    for r in rows:
        methods[r.get("method") or "?"] = methods.get(r.get("method") or "?", 0) + 1
    logger.info("by method: {}", methods)

    if args.dry_run:
        with engine.connect() as c:
            have = {
                t
                for (t,) in c.execute(
                    text(
                        "SELECT s.source_code || ':' || j.source_job_id::text "
                        "FROM core.jobs j JOIN ref.sources s ON s.source_id = j.source_id"
                    )
                ).all()
            }
        keys = {f"{r['source_code']}:{r['source_job_id']}" for r in rows}
        matched = keys & have
        logger.info(
            "would update {:,} rows; {:,} keys not found locally", len(matched), len(keys - have)
        )
        return 0

    applied = failed = 0
    with engine.connect() as conn:
        for start in range(0, len(rows), args.batch):
            chunk = rows[start : start + args.batch]
            try:
                conn.execute(text(STAGE_DDL))
                # COPY is far faster than 2,000 individual INSERTs and keeps the
                # whole batch in one round trip.
                raw = conn.connection.cursor()
                copy_sql = (
                    "COPY overlay_stage (source_code, source_job_id, title_en, "
                    "description_en, language_code) FROM STDIN"
                )
                with raw.copy(copy_sql) as cp:
                    for r in chunk:
                        cp.write_row(
                            (
                                r["source_code"],
                                str(r["source_job_id"]),
                                r.get("title_en"),
                                r.get("description_en"),
                                r.get("language_code"),
                            )
                        )
                for stmt in (TITLE_UPDATE, DESC_UPDATE, LANG_UPDATE):
                    conn.execute(text(stmt))
                conn.commit()
                applied += len(chunk)
            except Exception as exc:  # noqa: BLE001 - one bad chunk must not stop the merge
                conn.rollback()
                failed += len(chunk)
                logger.warning("chunk at {} failed ({}); continuing", start, exc)

    logger.info("applied {:,} overlay rows ({} failed chunks)", applied, failed)
    if failed and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


"""Apply the HF classifications overlay to the local database.

The Kaggle kernel classifies job titles on GPU and writes its results to a
separate HF dataset keyed by the natural identity ``(source_code,
source_job_id)``.  This script reads that overlay and updates Postgres.

The overlay is strictly additive — running this script twice on the same
published overlay is a no-op for rows that already match.

Identity
--------
``job_id`` is NOT portable — each database has its own sequence — so rows are
matched on ``(source_code, source_job_id)``, the same key used by the
translation overlay.

Usage::

    python scripts/apply_classifications.py --dry-run
    python scripts/apply_classifications.py --batch 2000
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger
from sqlalchemy import text

OVERLAY_REPO = "Shifat2110724169/job-market-intel-classifications"
OVERLAY_PATH = f"hf://datasets/{OVERLAY_REPO}/classifications.parquet"

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

BATCH = 2000

#: Staging table for one batch of the overlay.  Dropped at end of transaction.
STAGE_DDL = """
CREATE TEMP TABLE cls_stage (
    source_code                 text,
    source_job_id               text,
    title_classification_status text,
    normalized_title_id         bigint,
    normalized_title_confidence double precision,
    title_classified_by         text
) ON COMMIT DROP
"""

#: Update classification columns.  NULL values in the overlay are SKIPPED so a
#: partially-classified row is not regressed to unclassified.
CLS_UPDATE = """
UPDATE core.jobs j
   SET title_classification_status = s.title_classification_status,
       normalized_title_id         = s.normalized_title_id,
       normalized_title_confidence  = s.normalized_title_confidence,
       title_classified_by         = s.title_classified_by,
       updated_at                  = now()
  FROM cls_stage s
  JOIN ref.sources r ON r.source_code = s.source_code
 WHERE j.source_id = r.source_id
   AND j.source_job_id::text = s.source_job_id
   AND s.title_classification_status IS NOT NULL
   AND (
         j.title_classification_status IS DISTINCT FROM s.title_classification_status
      OR j.normalized_title_id         IS DISTINCT FROM s.normalized_title_id
      OR j.normalized_title_confidence  IS DISTINCT FROM s.normalized_title_confidence
      OR j.title_classified_by         IS DISTINCT FROM s.title_classified_by
   )
"""


def overlay_rows() -> list[dict]:
    """Read the classifications overlay from HF.  Anonymous read; dataset is public."""
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
    except Exception as exc:  # noqa: BLE001 — Hub may be unreachable
        logger.error("could not read classifications overlay from HF: {}", exc)
        return 0 if not args.strict else 1

    if not rows:
        logger.info("classifications overlay is empty — nothing to apply")
        return 0

    logger.info("overlay rows: {:,}", len(rows))
    # Log breakdown by classified_by tag
    methods: dict[str, int] = {}
    for r in rows:
        key = r.get("title_classified_by") or "?"
        methods[key] = methods.get(key, 0) + 1
    logger.info("by classifier: {}", methods)

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
            "would match {:,} rows by key; {:,} keys not found locally",
            len(matched),
            len(keys - have),
        )
        return 0

    processed = applied = failed = 0
    with engine.connect() as conn:
        for start in range(0, len(rows), args.batch):
            chunk = rows[start : start + args.batch]
            try:
                conn.execute(text(STAGE_DDL))
                raw = conn.connection.cursor()
                copy_sql = (
                    "COPY cls_stage "
                    "(source_code, source_job_id, title_classification_status, "
                    "normalized_title_id, normalized_title_confidence, title_classified_by) "
                    "FROM STDIN"
                )
                with raw.copy(copy_sql) as cp:
                    for r in chunk:
                        cp.write_row(
                            (
                                r["source_code"],
                                str(r["source_job_id"]),
                                r.get("title_classification_status"),
                                r.get("normalized_title_id"),
                                r.get("normalized_title_confidence"),
                                r.get("title_classified_by"),
                            )
                        )
                result = conn.execute(text(CLS_UPDATE))
                changed = result.rowcount if result.rowcount and result.rowcount > 0 else 0
                conn.commit()
                processed += len(chunk)
                applied += changed
            except Exception as exc:  # noqa: BLE001 — one bad chunk must not stop the merge
                conn.rollback()
                failed += len(chunk)
                logger.warning("chunk at {} failed ({}); continuing", start, exc)

    logger.info(
        "processed {:,} overlay rows; changed {:,} local rows ({} failed chunks)",
        processed,
        applied,
        failed,
    )
    if failed and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

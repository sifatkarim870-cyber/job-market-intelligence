"""Delete CI rows that are already safely on Hugging Face.

Why this exists
---------------
The corpus grows without bound. Measured 2026-10-11: 113,469 rows, 1,325 MB,
and ``core.job_descriptions`` alone carries 4,721 bytes of payload per row. CI
inserts roughly 6,400 rows a day across four scheduled runs, so an unpruned
CI database grows by ~28.8 MB/day.

That number decides which free tier this project can use. The identity slice
(``core.jobs`` + ``ref`` + ``salary``) measures 251 MB, leaving ~249 MB of
headroom inside Supabase's 500 MB cap -- about eight days. Oracle's Always
Free 200 GB block volume needs no pruning to fit, but an unbounded database is
still an operational liability on any provider, and on a small one it is the
difference between working and hitting the same wall Neon hit.

The rule for what is safe to delete
-----------------------------------
A row may be deleted once BOTH are true:

  1. it has been exported to a Hugging Face shard, and
  2. that shard is recorded in ``public.ci_merged_shards``, meaning the laptop
     has already folded it into the authoritative local corpus.

Condition 2 is what makes this safe rather than reckless. A shard on HF is not
by itself proof the row is safe: HF can be rolled back, and an unmerged shard
is the exact data-loss case that
``scripts/merge_incoming_shards.py`` exists to prevent. A row whose shard is on
HF but NOT yet merged is still only copy that exists, so it is kept.

Deduplication state survives
---------------------------
Deleting a job row does not lose the dedup key: this script never drops
``core.jobs``. It deletes the BULK (``core.job_descriptions``, ~1,058 MB of the
1,325 MB) for jobs whose shard is merged, and leaves the identity columns that
the scrapers actually check. That is what keeps a re-scraped posting correctly
detected as "already seen" instead of being re-inserted.

Safety
------
* ``--dry-run`` reports and writes nothing.
* ``--keep-days N`` refuses to delete anything newer than N days, as a floor
  under the merge cycle. Default 7.
* Deletes are batched and committed per batch, so a timeout cannot roll back
  hours of work.
* The reporting query is SELECT-only; nothing here invents a threshold.

Usage:
    python scripts/prune_exported_rows.py --dry-run
    python scripts/prune_exported_rows.py
    python scripts/prune_exported_rows.py --keep-days 14 --batch-size 500
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from job_market_intel.db.config import DatabaseConfig  # noqa: E402

#: Tables that hold the bulk and can be pruned for a merged job.
#: core.jobs is NOT in this list -- it carries the dedup key.
BULK_TABLES = ("core.job_descriptions", "salary.job_salaries")

LEDGER_TABLE = "public.ci_merged_shards"


def _engine(dsn: str | None):
    """Connect to the CI database, falling back to the configured default."""
    if dsn:
        return create_engine(dsn, connect_args={"connect_timeout": 15})
    cfg = DatabaseConfig.from_env()
    return create_engine(cfg.url, connect_args={"connect_timeout": 15})


def prunable_job_ids(conn, keep_days: int, limit: int | None = None) -> list[int]:
    """job_ids whose shard is MERGED and which are older than the keep window.

    Returns ids only -- the DELETE statements are built by the caller so the
    dry-run path shares exactly the same selection logic as the real one. A
    dry run that computes a different set than the run it previews is worse than
    no dry run at all.

    Age comes from ``core.jobs.first_scraped_at``, which is NOT NULL and
    populated on every row. ``core.scraping_sessions`` is not used for it:
    41,938 of 113,469 rows have ``last_scraping_session_id IS NULL`` (backfilled
    history predates the session bookkeeping), and an INNER JOIN to that table
    would silently exclude all of them from pruning forever.
    """
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=keep_days)
    sql = f"""
        SELECT j.job_id
        FROM core.jobs j
        WHERE j.first_scraped_at < :cutoff
          AND EXISTS (
              SELECT 1 FROM {LEDGER_TABLE} m
              WHERE m.source_code = (
                        SELECT src.source_code FROM ref.sources src
                        WHERE src.source_id = j.source_id)
                AND m.merged_at IS NOT NULL
          )
        ORDER BY j.job_id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(text(sql), {"cutoff": cutoff}).all()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only; delete nothing")
    ap.add_argument("--dsn", help="CI database DSN; defaults to the configured database")
    ap.add_argument(
        "--keep-days",
        type=int,
        default=7,
        help="never prune rows scraped within this many days (default 7)",
    )
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument(
        "--limit", type=int, help="cap the number of jobs pruned this run (for testing)"
    )
    args = ap.parse_args(argv)

    engine = _engine(args.dsn)

    with engine.connect() as conn:
        merged = conn.execute(
            text(f"SELECT count(*) FROM {LEDGER_TABLE}")
        ).scalar_one()

    logger.info("ledger holds {} merged shard(s)", merged)
    if merged == 0:
        # Nothing has been folded into the laptop yet, so nothing on this
        # database can be proven safe to delete. Say so rather than silently
        # pruning nothing.
        logger.warning(
            "no merged shards recorded -- refusing to prune. Rows whose shard is "
            "on HF but not yet merged are the only copy that exists."
        )
        return 1

    ids = prunable_job_ids(engine.connect(), args.keep_days, args.limit)
    logger.info(
        "{} job(s) older than {} days have a merged shard", f"{len(ids):,}", args.keep_days
    )

    if args.dry_run:
        logger.info("--dry-run: nothing deleted")
        return 0
    if not ids:
        logger.info("nothing to prune")
        return 0

    deleted = 0
    for start in range(0, len(ids), args.batch_size):
        batch = ids[start : start + args.batch_size]
        with engine.begin() as conn:
            for table in BULK_TABLES:
                # core.job_descriptions is partitioned by hash; the DELETE
                # cascades to the partitions automatically.
                res = conn.execute(
                    text(f"DELETE FROM {table} WHERE job_id = ANY(:ids)"), {"ids": batch}
                )
                deleted += res.rowcount or 0
        logger.info(
            "pruned {}/{} jobs ({} rows so far)",
            f"{start + len(batch):,}",
            f"{len(ids):,}",
            f"{deleted:,}",
        )

    logger.info("prune complete: {} rows deleted from {}", f"{deleted:,}", ", ".join(BULK_TABLES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

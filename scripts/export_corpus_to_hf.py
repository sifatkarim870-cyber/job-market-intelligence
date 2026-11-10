"""Re-export the ENTIRE local corpus to Hugging Face as one consistent snapshot.

Why this exists
---------------
The corpus shards are produced by a watermark-based incremental export that runs
in GitHub Actions against a throwaway CI database. That is the right mechanism
for "new rows appeared" -- but it is structurally incapable of reflecting a
CORRECTION made on the laptop. Today's location re-resolution changed 87,486
rows on the local database and, because nothing propagated, Hugging Face kept
serving the old values. The stated requirement is that local and HF always
agree, so a change in one must appear in the other.

This does the other half of that contract: a full, authoritative snapshot of
the LOCAL database, uploaded so HF matches local row for row.

CI rows arrive before this runs
-------------------------------
CI scrapes into an ephemeral container and publishes what it wrote as shards on
HF. ``scripts/sync_corpus_from_hf.py`` pulls those shards down and
``scripts/merge_incoming_shards.py`` folds them into local. ``run_corpus_sync.cmd``
does merge-then-export in that order, so by the time this script runs, local is
the single database of record.

Replace, not merge
------------------
The upload replaces every shard tree with one ``shards/`` tree built from local.
Keeping both ``shards/`` and ``shards_local/`` would double-count rows.

Safety
------
``--dry-run`` reports the row counts without uploading or deleting. Deletion
only touches ``shards/`` and ``shards_local/`` inside the corpus dataset --
never the dumps, the card, or the export state. DuckDB reads of the corpus
keep working because the path shape (``source=``/``dt=`` partitions) is
identical.

Usage:
    python scripts/export_corpus_to_hf.py --dry-run
    python scripts/export_corpus_to_hf.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import shutil
import sys
import tempfile

from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from job_market_intel.corpus.shard_export import (  # noqa: E402
    SHARD_SELECT,
    to_arrow,
)

REPO = "Shifat2110724169/job-market-intel-corpus"

#: The database of record. ``LOCAL_DATABASE_URL`` wins so a machine can point at
#: a differently named local database without editing the script.
LOCAL_DSN = (
    os.environ.get("LOCAL_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
)

SHARD_TREES = ("shards", "shards_local")


def local_token() -> str:
    """HF token from the environment, else the laptop's token file."""
    for var in ("CORPUS_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    p = pathlib.Path(
        r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
    )
    return p.read_text(encoding="utf-8").strip()


def _sources_of(engine) -> set[str]:
    """Every source code that actually HAS rows -- not ref.sources.is_active.

    Filtering on is_active silently drops reed (2,361) and indeed (181), which
    are flagged inactive but still hold corpus rows, and that is exactly the
    "local and HF must match" contract being violated.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT s.source_code FROM core.jobs j "
                "JOIN ref.sources s ON s.source_id = j.source_id ORDER BY s.source_code"
            )
        ).all()
    return {r[0] for r in rows}


def _fetch_source(engine, code: str) -> list[tuple]:
    sql = SHARD_SELECT + " WHERE s.source_code = :code"
    with engine.connect() as conn:
        return conn.execute(text(sql), {"code": code}).all()


def check_against_database(rows: int, engine) -> None:
    """Log how the snapshot compares to the database. Never raises.

    The database count is read HERE, after ``build()`` has run, not before it.
    A count taken earlier describes an older database than the one that was just
    read: a local scraper or merge_incoming_shards.py can commit rows while the
    snapshot is being assembled, and the earlier count then reports a shortfall
    that is growth rather than loss.

    A shortfall is warned about, not fatal. The original check refused to publish
    outright, which turned a benign race into a failed daily sync; the rows
    involved are picked up by the next run.
    """
    with engine.connect() as conn:
        db_rows = conn.execute(text("SELECT count(*) FROM core.jobs")).scalar_one()

    logger.info(
        "snapshot {} rows vs local database {} rows",
        f"{rows:,}",
        f"{db_rows:,}",
    )

    if rows == db_rows:
        logger.info("snapshot row count matches the database exactly")
    elif rows < db_rows:
        logger.warning(
            "snapshot is {} rows behind the database, which grew while the export "
            "ran; those rows ship on the next run",
            f"{db_rows - rows:,}",
        )
    else:
        logger.warning(
            "snapshot has {} MORE rows than the database; check for an orphaned "
            "description or salary join",
            f"{rows - db_rows:,}",
        )


def build(engine, work: pathlib.Path, dt_partition: str) -> tuple[int, int, list[str]]:
    """Write one shard per source from the local database.

    Returns (rows, bytes, source codes written).
    """
    import pyarrow.parquet as pq

    codes = _sources_of(engine)
    total_rows = total_bytes = 0
    written: list[str] = []
    for code in sorted(codes):
        rows = _fetch_source(engine, code)
        if not rows:
            logger.info("  {:<16} 0 rows", code)
            continue

        table = to_arrow(rows, "local")
        out = work / "shards" / f"source={code}" / f"dt={dt_partition}" / "part-0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out, compression="snappy")
        total_rows += len(rows)
        total_bytes += out.stat().st_size
        written.append(code)
        logger.info(
            "  {:<16} {:>7,} rows  {:>8.1} KB",
            code,
            len(rows),
            out.stat().st_size / 1024,
        )
    return total_rows, total_bytes, written


def _source_of_shard(path: str) -> str | None:
    """``shards/source=jobvision/dt=.../part-0.parquet`` -> ``jobvision``."""
    match = re.match(r"^(?:shards|shards_local)/source=([^/]+)/", path)
    return match.group(1) if match else None


def deletable_shards(
    existing: list[str],
    written: list[str],
    uploaded: set[str],
    *,
    rows: int,
) -> list[str]:
    """Shard files that are safe to delete after this snapshot upload.

    Two refusals, each earned by a real incident:

    * **empty snapshot** -- an empty database must never be allowed to clean
      the corpus.
    * **source not written this run** -- a source that returned no rows (or was
      skipped) keeps its old shards. Cleaning it up would turn a transient read
      problem into permanent loss; a human can prune deliberately later.

    Only shards for a source that *was* written are candidates, and the path
    just uploaded is never deleted.
    """
    if rows == 0:
        return []
    written_set = set(written)
    out: list[str] = []
    for path in existing:
        if not path.endswith(".parquet"):
            continue
        if path.split("/", 1)[0] not in SHARD_TREES:
            continue
        code = _source_of_shard(path)
        if code is None or code not in written_set:
            continue
        if path in uploaded:
            continue
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--keep-local-tree",
        action="store_true",
        help="do not delete shards_local/ (legacy tree; normally removed)",
    )
    args = ap.parse_args(argv)

    engine = create_engine(LOCAL_DSN)
    dt_partition = dt.datetime.now(dt.UTC).date().isoformat()

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_snapshot_"))
    try:
        logger.info("building snapshot from LOCAL -> {}", work)
        rows, nbytes, sources_written = build(engine, work, dt_partition)
        logger.info(
            "built {} rows / {:.1f} MB across {} shards",
            f"{rows:,}",
            nbytes / 1e6,
            len(sources_written),
        )

        # The whole point of this script: the database and HF must agree.
        check_against_database(rows, engine)

        if args.dry_run:
            logger.info("--dry-run: nothing uploaded or deleted")
            return 0

        from huggingface_hub import HfApi, CommitOperationDelete

        api = HfApi(token=local_token())
        existing = list(api.list_repo_files(REPO, repo_type="dataset"))
        stale = [
            f for f in existing if f.endswith(".parquet") and f.split("/", 1)[0] in SHARD_TREES
        ]

        # Determine which old shards will become superseded once we upload.
        uploaded = {
            f"shards/source={code}/dt={dt_partition}/part-0.parquet" for code in sources_written
        }
        delete = deletable_shards(
            stale,
            sources_written,
            uploaded,
            rows=rows,
        )
        if rows == 0:
            logger.warning("snapshot is empty; refusing to delete any shard")
        elif not delete:
            logger.info("no superseded shards to delete")
        if args.keep_local_tree:
            delete = [f for f in delete if not f.startswith("shards_local/")]

        logger.info("uploading snapshot to {}", REPO)
        api.upload_folder(
            folder_path=str(work / "shards"),
            repo_id=REPO,
            repo_type="dataset",
            path_in_repo="shards",
            commit_message=f"full local snapshot {dt_partition}: {rows:,} rows",
        )
        if delete:
            logger.info("deleting {} superseded shard file(s) in one commit", len(delete))
            api.create_commit(
                repo_id=REPO,
                repo_type="dataset",
                commit_message=f"full local snapshot {dt_partition}: {rows:,} rows — prune superseded shards",
                operations=[CommitOperationDelete(path_in_repo=f) for f in delete],
            )

        logger.info("done: HF now mirrors {} local rows", f"{rows:,}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
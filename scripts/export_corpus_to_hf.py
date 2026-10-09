"""Re-export the ENTIRE local corpus to Hugging Face as one consistent snapshot.

Why this exists
---------------
The corpus shards are produced by a watermark-based incremental export that
runs in GitHub Actions against Neon. That is the right mechanism for "new
rows appeared" -- but it is structurally incapable of reflecting a CORRECTION
made on the laptop. Today's location re-resolution changed 87,486 rows on the
local database and, because nothing propagated, Hugging Face kept serving the
old values. The stated requirement is that local and HF always agree, so a
change in one must appear in the other.

This does the other half of that contract: a full, authoritative snapshot of
the LOCAL database, uploaded so HF matches local row for row.

Replace, not merge
------------------
HF holds two trees today -- ``shards/`` (rows scraped by CI against Neon) and
``shards_local/`` (rows that only ever existed on the laptop). Since the Neon
rows were merged into local, local is now a strict superset, so keeping both
would double-count every CI row. The upload therefore replaces both trees
with one ``shards/`` tree built from local.

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
import pathlib
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
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

#: Both trees are replaced: local is a strict superset of the Neon rows now,
#: so leaving shards/ in place would duplicate every CI-scraped row.
SHARD_TREES = ("shards", "shards_local")


def local_token() -> str:
    p = pathlib.Path(
        r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
    )
    return p.read_text(encoding="utf-8").strip()


def build(engine, work: pathlib.Path, dt_partition: str) -> tuple[int, int, list[str]]:
    """Write one shard per source. Returns (rows, bytes, source codes written)."""
    import pyarrow.parquet as pq

    with engine.connect() as conn:
        # Every source that actually HAS rows -- not ref.sources.is_active.
        # Filtering on is_active silently drops reed (2,361) and indeed (181),
        # which are flagged inactive but still hold corpus rows, and that is
        # exactly the "local and HF must match" contract being violated.
        sources = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT DISTINCT s.source_code FROM core.jobs j "
                    "JOIN ref.sources s ON s.source_id = j.source_id "
                    "ORDER BY s.source_code"
                )
            ).all()
        ]

    total_rows = total_bytes = 0
    written: list[str] = []
    for code in sources:
        sql = SHARD_SELECT + " WHERE s.source_code = :code"
        with engine.connect() as conn:
            rows = conn.execute(text(sql), {"code": code}).all()
        if not rows:
            logger.info("  {:<16} 0 rows", code)
            continue
        table = to_arrow(rows, origin="local")
        out = work / "shards" / f"source={code}" / f"dt={dt_partition}" / "part-0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out, compression="snappy")
        total_rows += len(rows)
        total_bytes += out.stat().st_size
        written.append(code)
        logger.info("  {:<16} {:>7,} rows  {:>8.1} KB", code, len(rows), out.stat().st_size / 1024)
    return total_rows, total_bytes, written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--keep-local-tree",
        action="store_true",
        help="do not delete shards_local/ (will double-count CI rows)",
    )
    args = ap.parse_args(argv)

    engine = create_engine(LOCAL_DSN)
    dt_partition = dt.datetime.now(dt.UTC).date().isoformat()

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_snapshot_"))
    try:
        logger.info("building snapshot from the LOCAL database -> {}", work)
        rows, nbytes, sources_written = build(engine, work, dt_partition)
        logger.info(
            "built {} rows / {:.1f} MB across {} shards",
            f"{rows:,}",
            nbytes / 1e6,
            len(sources_written),
        )

        # The whole point of this script: local and HF must agree. Compare the
        # snapshot against the database it came from before publishing it.
        with engine.connect() as conn:
            db_rows = conn.execute(text("SELECT count(*) FROM core.jobs")).scalar_one()
        if rows != db_rows:
            logger.error(
                "snapshot has {} rows but core.jobs has {} -- refusing to publish",
                f"{rows:,}",
                f"{db_rows:,}",
            )
            return 1
        logger.info("row count matches core.jobs ({:,})", db_rows)

        if args.dry_run:
            logger.info("--dry-run: nothing uploaded or deleted")
            return 0

        from huggingface_hub import HfApi

        api = HfApi(token=local_token())
        existing = api.list_repo_files(REPO, repo_type="dataset")
        stale = [
            f for f in existing if f.endswith(".parquet") and f.split("/", 1)[0] in SHARD_TREES
        ]
        logger.info("uploading snapshot to {}", REPO)
        api.upload_folder(
            folder_path=str(work / "shards"),
            repo_id=REPO,
            repo_type="dataset",
            path_in_repo="shards",
            commit_message=f"full local snapshot {dt_partition}: {rows:,} rows",
        )

        # Only delete shard files this run did NOT just write. The snapshot's
        # dt= partition can collide with today's existing one, so filtering by
        # path alone would remove the files that were uploaded moments ago.
        uploaded = {
            f"shards/source={code}/dt={dt_partition}/part-0.parquet" for code in sources_written
        }
        delete = [f for f in stale if f not in uploaded]
        if args.keep_local_tree:
            delete = [f for f in delete if not f.startswith("shards_local/")]
        if delete:
            logger.info("deleting {} superseded shard file(s)", len(delete))
            for i in range(0, len(delete), 50):
                # NOTE: delete_files(repo_id, delete_patterns, ...) -- repo id
                # first. Passing the list positionally sends the file list as
                # the repo id and raises HFValidationError.
                api.delete_files(REPO, delete[i : i + 50], repo_type="dataset")

        logger.info("done: HF now mirrors {} local rows", f"{rows:,}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

#: The corpus is the UNION of the two databases, not a copy of either.
#:
#: This script used to export from local alone, on the documented assumption
#: that "local is now a strict superset" of Neon. That was true once, right after
#: the one-time Neon merge, and stopped being true the moment CI scraped
#: anything new: CI writes to Neon (secrets.DATABASE_URL), which never flows back
#: into the laptop database.
#:
#: Measured on 2026-10-11, neither is a superset:
#:
#:     local-only: jobvision +46,982   greenhouse +5,325   jobinja +207
#:     neon-only : glints     +3,183    51job      +857    jobmaster +635
#:                 irantalent     +400    arbeitnow  +350   hrge      +169
#:
#: Exporting local only therefore DELETED 5,321 rows from HF -- real CI-scraped
#: postings that exist on Neon and on the laptop not at all. Both are read and
#: merged by natural key, local's row winning a tie so the laptop's derived
#: columns (requirements, responsibilities, skills) survive.
SHARD_TREES = ("shards", "shards_local")

#: Where DATABASE_URL is read from. A module constant rather than a derived path
#: so tests can point it at a fixture .env without touching the real one.
ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"


def neon_dsn() -> str | None:
    """Neon DSN from ``ENV_PATH``, or None when absent/unusable."""
    env = pathlib.Path(ENV_PATH)
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*DATABASE_URL\s*=\s*(.+)$", line)
        if not m:
            continue
        url = m.group(1).strip().strip('"').strip("'")
        # Accept every spelling seen in the wild: the already-normalised psycopg
        # form .env itself uses, plain postgresql:// from psql tooling, and
        # postgres:// from Heroku-style connection strings.
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix) :]
                break
        else:
            return None
        # The same URL as local would be a misconfiguration, not a second DB.
        if url == LOCAL_DSN:
            return None
        return url
    return None


def local_token() -> str:
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


#: SHARD_SELECT column order: 0 = source_job_id, 1 = source_code.
_JOB_KEY = (1, 0)


def _merge_source(local_rows: list[tuple], neon_rows: list[tuple]) -> tuple[list[tuple], list[str]]:
    """Union both databases for one source, keyed on (source_code, source_job_id).

    ``job_id`` is deliberately NOT the key: each database has its own sequence, so
    local job 12345 and Neon job 12345 are unrelated postings. Every identity here
    is the natural key.

    On a tie, LOCAL wins. The laptop is where the derived columns
    (requirements, responsibilities, required_skills_text) were backfilled, so
    taking Neon's copy would silently blank them for every row both databases
    share -- which is most of them.
    """
    merged: dict[tuple[str, str], tuple[tuple, str]] = {}
    origins: list[str] = []
    for row in neon_rows:
        key = (row[_JOB_KEY[0]], row[_JOB_KEY[1]])
        merged[key] = (row, "neon")
    for row in local_rows:  # last, so local overwrites
        key = (row[_JOB_KEY[0]], row[_JOB_KEY[1]])
        merged[key] = (row, "local")
    rows = [pair[0] for pair in merged.values()]
    origins = [pair[1] for pair in merged.values()]
    return rows, origins


def build(
    engine,
    work: pathlib.Path,
    dt_partition: str,
    neon_engine=None,
) -> tuple[int, int, list[str]]:
    """Write one shard per source, as the union of both databases.

    Returns (rows, bytes, source codes written).
    """
    import pyarrow.parquet as pq

    codes = _sources_of(engine)
    if neon_engine is not None:
        codes |= _sources_of(neon_engine)

    total_rows = total_bytes = 0
    written: list[str] = []
    for code in sorted(codes):
        local_rows = _fetch_source(engine, code)
        neon_rows = _fetch_source(neon_engine, code) if neon_engine is not None else []
        if not local_rows and not neon_rows:
            logger.info("  {:<16} 0 rows", code)
            continue

        rows, origins = _merge_source(local_rows, neon_rows)
        only_local = sum(1 for o in origins if o == "local")
        only_neon = len(origins) - only_local
        table = to_arrow(rows, origins)
        out = work / "shards" / f"source={code}" / f"dt={dt_partition}" / "part-0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out, compression="snappy")
        total_rows += len(rows)
        total_bytes += out.stat().st_size
        written.append(code)
        logger.info(
            "  {:<16} {:>7,} rows ({:,} local / {:,} neon-only)  {:>8.1} KB",
            code,
            len(rows),
            only_local,
            only_neon,
            out.stat().st_size / 1024,
        )
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

    # Read Neon too, so the snapshot is the union rather than a copy of whichever
    # database happens to be reachable. A Neon outage degrades to local-only with
    # a loud warning -- it must not fail the export, or a transient Hub/DB problem
    # would leave HF stale.
    neon_engine = None
    dsn = neon_dsn()
    if dsn:
        try:
            probe = create_engine(dsn, connect_args={"connect_timeout": 10})
            with probe.connect() as conn:
                conn.execute(text("SELECT 1"))
            neon_engine = probe
            logger.info("merging Neon as a second source: {}", dsn.split("@")[-1].split("/")[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neon unreachable ({}); exporting local only", str(exc)[:120])
    else:
        logger.warning("no DATABASE_URL in .env; exporting local only")

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_snapshot_"))
    try:
        logger.info("building snapshot from LOCAL + Neon -> {}", work)
        rows, nbytes, sources_written = build(engine, work, dt_partition, neon_engine)
        logger.info(
            "built {} rows / {:.1f} MB across {} shards",
            f"{rows:,}",
            nbytes / 1e6,
            len(sources_written),
        )

        # The whole point of this script: the database(s) and HF must agree.
        #
        # This used to assert snapshot == local core.jobs, and that check is
        # exactly what let 5,321 rows be deleted from HF while everything still
        # passed: the count matched, the columns matched, and the data was gone.
        # The snapshot is now the union of local and Neon, so it is compared
        # against the union -- and any Neon-only row is logged, because that is
        # the number that says whether the second database is being read at all.
        with engine.connect() as conn:
            db_rows = conn.execute(text("SELECT count(*) FROM core.jobs")).scalar_one()
        neon_db_rows = 0
        if neon_engine is not None:
            with neon_engine.connect() as conn:
                neon_db_rows = conn.execute(
                    text("SELECT count(*) FROM core.jobs")
                ).scalar_one()

        neon_only = rows - db_rows
        logger.info(
            "snapshot {} rows = local {} + Neon-only {} (Neon itself holds {})",
            f"{rows:,}",
            f"{db_rows:,}",
            f"{neon_only:,}",
            f"{neon_db_rows:,}",
        )
        if neon_engine is None and rows == db_rows:
            logger.warning(
                "Neon was not read; the snapshot is local only. Any row scraped "
                "by CI into Neon is missing from HF."
            )
        if rows < db_rows:
            logger.error(
                "snapshot has {} rows but core.jobs has {} -- refusing to publish",
                f"{rows:,}",
                f"{db_rows:,}",
            )
            return 1

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

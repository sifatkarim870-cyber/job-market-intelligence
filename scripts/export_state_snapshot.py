"""Publish the state CI needs to run without a cloud database.

Replaces the Neon dependency. Neon's free quota is exhausted ("Your account or
project has exceeded the quota"), and every hosted free Postgres has some quota
that will eventually bite the same way -- Supabase's is 500 MB, Neon's is compute
time, and both are silent until a scrape suddenly cannot write.

So CI no longer uses a hosted database at all. It gets an EPHEMERAL Postgres
service container, seeded from this snapshot:

    state/schema.sql         full DDL, pg_dump --schema-only of local
    state/reference.parquet  ref.* + bridge.* + core.companies + company aliases

reference is deliberately the whole of ref.* rather than the subset a scraper
touches: it is 1,279 rows, so shipping all of it costs nothing and a source that
needs something unusual does not fail confusingly.

What is NOT shipped: core.jobs. Deduplication state cannot be seeded there
without lying to the schema -- core.jobs has no unique constraint on
(source_id, source_job_id) alone, only on (source_id, source_job_id,
posting_date), and eight NOT NULL columns with no default that would need
sentinel values. Faking those rows would also corrupt every analytics query over
them.

So CI's run is a fresh view of its capped window rather than an incremental
diff, and the merge step (scripts/merge_incoming_shards.py) does the dedup by
natural key. Every scraper already caps its window -- jobvision 400, greenhouse
1,000, hrge 700 -- so a run touches a few thousand rows at most, which is cheap
to re-read each time.

Usage:
    uv run python scripts/export_state_snapshot.py --dry-run
    uv run python scripts/export_state_snapshot.py
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import HfApi
from loguru import logger
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPO = "Shifat2110724169/job-market-intel-corpus"
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
STATE_PREFIX = "state/"


def local_token() -> str:
    p = pathlib.Path(
        r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
    )
    return p.read_text(encoding="utf-8").strip()


def _dump_schema(work: pathlib.Path) -> pathlib.Path:
    """pg_dump --schema-only of local. Kept in the repo so CI never depends on
    the laptop being reachable."""
    out = work / "schema.sql"
    subprocess = _import_subprocess()
    env = os.environ.copy()
    env["PGPASSWORD"] = "changeme"
    subprocess.run(
        [
            str(_pg_dump_binary()),
            "-h",
            "localhost",
            "-p",
            "5432",
            "-U",
            "app_user",
            "-d",
            "job_market_intelligence",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(out),
        ],
        check=True,
        env=env,
    )
    _strip_session_settings(out)
    return out


#: Session GUCs pg_dump writes as a prelude. `transaction_timeout` only exists
#: from PostgreSQL 18 on, so a dump taken on 18 makes a 16 (or 17) container
#: abort with "unrecognized configuration parameter". None of them are schema
#: state: they are the client session's defaults, and the restored database gets
#: its own server defaults instead.
_SESSION_SETTINGS = (
    "transaction_timeout",
    "statement_timeout",
    "lock_timeout",
    "idle_in_transaction_session_timeout",
)


def _strip_session_settings(path: pathlib.Path) -> int:
    """Drop the pg_dump session-settings prelude so the file is version-portable."""
    import re

    pattern = re.compile(
        r"^\s*SET\s+(" + "|".join(_SESSION_SETTINGS) + r")\s*=\s*[^;]*;\s*$",
        re.IGNORECASE,
    )
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if not pattern.match(line)]
    removed = len(lines) - len(kept)
    if removed:
        path.write_text("".join(kept), encoding="utf-8")
    return removed


def _import_subprocess():
    import subprocess

    return subprocess


def _pg_dump_binary() -> pathlib.Path:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates = sorted(
        pathlib.Path(program_files, "PostgreSQL").glob("*/bin/pg_dump.exe"), reverse=True
    )
    if not candidates:
        raise SystemExit("pg_dump.exe not found; install PostgreSQL client tools")
    return candidates[0]


def _reference_tables(engine) -> list[tuple[str, str]]:
    """Every table CI needs seeded, as (schema, table) pairs.

    Only ``ref`` and ``bridge`` are shipped, and only the lookups: everything in
    ``core`` is either the corpus itself (jobs, job_descriptions, or their
    partitions), a cache the resolver rebuilds (location_aliases), or a table
    whose identity column is GENERATED ALWAYS and therefore cannot be inserted
    across databases (companies, job_skills).

    Shipping ref.* is enough for a scrape to run: it carries the source registry,
    the country/city/region vocabulary, currencies, and the skill taxonomy. CI's
    database is ephemeral, so company resolution and location resolution run
    fresh and the ids they invent die with the container -- which is correct,
    because the only thing that leaves CI is the newly scraped rows.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT n.nspname, c.relname "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind = 'r' "
                "  AND n.nspname IN ('ref', 'bridge') "
                "  AND NOT c.relispartition "
                "ORDER BY 1, 2"
            )
        ).all()
    pairs = [(s, t) for s, t in rows]
    # Derived from jobs, FK to core.jobs, rebuilt on every write.
    _EXCLUDED = {"job_skills", "job_languages"}
    return [(s, t) for s, t in pairs if t not in _EXCLUDED]


def _write_parquet(engine, schema: str, table: str, out: pathlib.Path) -> int:
    """Dump one table to parquet, preserving column order."""
    with engine.connect() as conn:
        columns = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
                ),
                {"s": schema, "t": table},
            ).all()
        ]
        rows = conn.execute(
            text(f'SELECT * FROM "{schema}"."{table}"')  # noqa: S608
        ).all()
    if not rows:
        return 0
    table_obj = pa.table({c: pa.array([r[i] for r in rows]) for i, c in enumerate(columns)})
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table_obj, out, compression="zstd")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="build locally, upload nothing")
    args = ap.parse_args()

    engine = create_engine(LOCAL_DSN)
    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_state_"))
    try:
        schema = _dump_schema(work)
        kbytes = schema.stat().st_size / 1024
        logger.info("schema.sql  {:.1f} KB", kbytes)

        ref_dir = work / "reference"
        total_ref = 0
        for s, t in _reference_tables(engine):
            n = _write_parquet(engine, s, t, ref_dir / f"{s}.{t}.parquet")
            total_ref += n
        logger.info(
            "reference   {:,} rows across {} tables",
            total_ref,
            len(list(ref_dir.glob("*.parquet"))),
        )

        if args.dry_run:
            logger.info("--dry-run: nothing uploaded")
            return 0

        api = HfApi(token=local_token())
        for path in [schema, *sorted(ref_dir.glob("*.parquet"))]:
            api.upload_file(
                path_or_fileobj=str(path),
                path_in_repo=f"{STATE_PREFIX}{path.name}",
                repo_id=REPO,
                repo_type="dataset",
            )
            logger.info("uploaded {}", path.name)
        logger.info("state snapshot published to {}:{}", REPO, STATE_PREFIX)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

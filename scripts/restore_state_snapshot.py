"""Restore a state snapshot into a target database.

The other half of scripts/export_state_snapshot.py. CI calls it against an
ephemeral Postgres service container so a scrape can run with no hosted database
at all -- Neon's free quota is exhausted, and every hosted free Postgres has a
quota that will eventually do the same thing.

Usage:
    uv run python scripts/restore_state_snapshot.py --dsn <target> --source hf
    uv run python scripts/restore_state_snapshot.py --dsn <target> --state-dir <path>

``--source hf`` downloads state/ from the corpus dataset repo. ``--state-dir``
reads a local copy, which is how the round-trip is tested.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile
from urllib.parse import urlsplit

import pyarrow.parquet as pq
from loguru import logger
from sqlalchemy import create_engine, text

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
REPO = "Shifat2110724169/job-market-intel-corpus"
STATE_PREFIX = "state/"
#: Where the write token is read from when the environment does not supply one.
#: A hardcoded Windows path here once made every CI job fail on a machine that
#: has no such path -- see _resolve_token().
TOKEN_FILE = pathlib.Path(
    r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
)


def _resolve_token() -> str:
    """HF token from the environment, else the token file.

    HF_TOKEN is present in CI and in local runs that need it, so the file is
    only a laptop convenience. Reading the file first made the restore script
    fail on any machine without it -- including every GitHub runner.
    """
    import os

    env_token = os.environ.get("HF_TOKEN")
    if env_token:
        return env_token
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "HF_TOKEN is not set and the token file is missing. "
        "Set HF_TOKEN, or place one at " + str(TOKEN_FILE)
    )


def download_state(work: pathlib.Path) -> pathlib.Path:
    from huggingface_hub import HfApi

    api = HfApi(token=_resolve_token())
    names = sorted(
        n for n in api.list_repo_files(REPO, repo_type="dataset") if n.startswith(STATE_PREFIX)
    )
    dest = work / "state"
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        local = api.hf_hub_download(
            repo_id=REPO, repo_type="dataset", filename=name, token=_resolve_token()
        )
        shutil.copy(local, dest / name[len(STATE_PREFIX) :])
        logger.info("downloaded {}", name[len(STATE_PREFIX) :])
    return dest


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _psql_binary() -> pathlib.Path:
    """Locate psql. Windows needs the versioned PostgreSQL install; the GitHub
    ubuntu runner image already ships psql on PATH."""
    env_override = os.environ.get("PSQL_BIN")
    if env_override:
        return pathlib.Path(env_override)
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates = sorted(
            pathlib.Path(program_files, "PostgreSQL").glob("*/bin/psql.exe"), reverse=True
        )
        return candidates[0] if candidates else pathlib.Path("psql")
    return pathlib.Path("psql")


def apply_schema(engine, schema_sql: pathlib.Path) -> None:
    """Run the DDL with psql.

    Splitting on semicolons and executing statement-by-statement was tried first
    and does not work: pg_dump emits statements the naive split mangles, such as
    ``CREATE TYPE job_status AS ENUM (...)`` -- the split left a fragment ending
    mid-clause and Postgres rejected it with a bare "syntax error at or near
    Type". psql already parses this format, so it does the work.
    """
    import subprocess

    url = urlsplit(engine.url.render_as_string(hide_password=False))
    env = os.environ.copy()
    env["PGPASSWORD"] = url.password or ""
    subprocess.run(
        [
            str(_psql_binary()),
            "-h",
            url.hostname or "localhost",
            "-p",
            str(url.port or 5432),
            "-U",
            url.username or "postgres",
            "-d",
            (url.path or "/postgres").lstrip("/"),
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(schema_sql),
        ],
        check=True,
        env=env,
        capture_output=True,
    )
    logger.info("schema applied from {}", schema_sql.name)


def _dependencies(conn, pair: tuple[str, str]) -> list[tuple[str, str]]:
    """Tables ``pair`` references by foreign key."""
    rows = conn.execute(
        text(
            "SELECT ns.nspname, cls.relname FROM pg_constraint c "
            "JOIN pg_class cls ON cls.oid = c.confrelid "
            "JOIN pg_namespace ns ON ns.oid = cls.relnamespace "
            "WHERE c.conrelid = to_regclass(:reg) AND c.contype = 'f'"
        ),
        {"reg": f"{pair[0]}.{pair[1]}"},
    ).all()
    return [(r[0], r[1]) for r in rows]


def _sort_by_dependency(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Order tables so a table's foreign keys are already inserted.

    Alphabetical order is wrong: ref.cities sorts before ref.countries and
    references it, so a plain loop fails with "insert on table cities violates
    cities_country_id_fkey".

    The underlying connection is closed by the time this is called, so the graph
    cannot be read here from the catalog -- the caller opens one. A
    self-reference (job_categories.parent_category_id -> job_categories) is
    handled by disabling its trigger during the load; see restore_reference.
    """
    return list(pairs)


def _relax_identity_columns(conn, schema: str, table: str) -> None:
    """Switch GENERATED ALWAYS identity columns to BY DEFAULT.

    Postgres refuses an explicit value for those ("cannot insert a non-DEFAULT
    value into column benefit_id"), which would strand every foreign key pointing
    at them -- ref.locations -> ref.cities/regions would no longer line up.
    """
    for column in _always_identity_columns(conn, schema, table):
        conn.execute(
            text(
                f"ALTER TABLE {schema}.{_quote_identifier(table)} "
                f"ALTER COLUMN {_quote_identifier(column)} SET GENERATED BY DEFAULT"
            )
        )


def _load_table(conn, schema: str, table: str, table_obj) -> None:
    """Truncate then insert one reference table, tolerating self-references."""
    conn.execute(text(f"TRUNCATE {schema}.{_quote_identifier(table)} CASCADE"))
    # A table can reference itself (job_categories.parent_category_id), where no
    # row order satisfies the constraint. Its FK trigger is disabled for the
    # load and re-enabled after -- safe, because the rows come from a database
    # where they were already valid.
    self_referencing = any(d == (schema, table) for d in _dependencies(conn, (schema, table)))
    if self_referencing:
        conn.execute(text(f"ALTER TABLE {schema}.{_quote_identifier(table)} DISABLE TRIGGER ALL"))
    try:
        columns = table_obj.column_names
        values = list(zip(*[table_obj.column(c).to_pylist() for c in columns], strict=True))
        statement = text(
            f"INSERT INTO {schema}.{_quote_identifier(table)} "
            f"({', '.join(_quote_identifier(c) for c in columns)}) "
            f"VALUES ({', '.join(f':{c}' for c in columns)})"
        )
        for start in range(0, len(values), 1000):
            chunk = values[start : start + 1000]
            conn.execute(statement, [dict(zip(columns, r, strict=True)) for r in chunk])
    finally:
        if self_referencing:
            conn.execute(
                text(f"ALTER TABLE {schema}.{_quote_identifier(table)} ENABLE TRIGGER ALL")
            )


def restore_reference(engine, state_dir: pathlib.Path) -> int:
    """Load every reference parquet back into its own table, parents first.

    Globs recursively: the local build writes them under ``reference/``, while a
    downloaded snapshot has them flat in ``state/``. Both layouts work.

    Three distinct database realities are handled here, each of which was hit in
    turn while getting this working:

    1. Identity columns declared GENERATED ALWAYS refuse an explicit value
       ("cannot insert a non-DEFAULT value into benefit_id"), which would strand
       every FK pointing at them -- ref.locations -> ref.cities/regions would no
       longer line up. They are switched to GENERATED BY DEFAULT first, so the
       original ids survive.
    2. Insert order matters: ref.cities must follow ref.countries. Tables are
       sorted by their foreign keys, read from the catalog.
    3. A table can reference itself (job_categories.parent_category_id), where
       no row order works. Its FK trigger is disabled for the load and re-enabled
       after -- safe, because the rows come from a database where they were
       already valid.
    """
    total = 0
    with engine.begin() as conn:
        by_table: dict[tuple[str, str], pathlib.Path] = {}
        for path in sorted(state_dir.glob("**/*.parquet")):
            if path.name == "job_identities.parquet" or "." not in path.stem:
                continue
            schema, table = path.stem.split(".", 1)
            by_table[(schema, table)] = path

        ordered: list[tuple[str, str]] = []
        remaining = list(by_table)
        while remaining:
            progressed = False
            for pair in list(remaining):
                # A self-reference is handled by disabling the trigger below,
                # not by ordering.
                blocking = [d for d in _dependencies(conn, pair) if d in remaining and d != pair]
                if blocking:
                    continue
                ordered.append(pair)
                remaining.remove(pair)
                progressed = True
            if not progressed:
                ordered.extend(remaining)
                break

        for schema, table in ordered:
            path = by_table[(schema, table)]
            table_obj = pq.read_table(path)
            if table_obj.num_rows == 0:
                continue
            _relax_identity_columns(conn, schema, table)
            _load_table(conn, schema, table, table_obj)
            total += table_obj.num_rows
    logger.info("restored {:,} reference rows", total)
    return total


def _always_identity_columns(conn, schema: str, table: str) -> list[str]:
    """Identity columns declared GENERATED ALWAYS, which cannot be inserted."""
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            "  AND is_identity = 'YES' AND identity_generation = 'ALWAYS'"
        ),
        {"s": schema, "t": table},
    ).all()
    return [r[0] for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default=LOCAL_DSN)
    ap.add_argument("--source", choices=["hf", "dir"], default="hf")
    ap.add_argument("--state-dir", help="local state directory (with --source dir)")
    ap.add_argument("--skip-schema", action="store_true")
    args = ap.parse_args()

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_restore_"))
    try:
        state_dir = pathlib.Path(args.state_dir) if args.source == "dir" else download_state(work)
        schema_sql = state_dir / "schema.sql"
        if not schema_sql.exists():
            raise SystemExit(f"{schema_sql} missing from the state snapshot")

        engine = create_engine(args.dsn)
        if not args.skip_schema:
            apply_schema(engine, schema_sql)
        restore_reference(engine, state_dir)
        logger.info("state snapshot restored into {}", args.dsn.split("@")[-1])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

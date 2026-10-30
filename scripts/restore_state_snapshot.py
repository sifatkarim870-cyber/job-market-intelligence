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
import random
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from typing import TypeVar
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


T = TypeVar("T")

#: HuggingFace answers 429 ("Too Many Requests") when more than a handful of
#: calls arrive at once. A full Scrape (HTML) run starts ~97 matrix jobs, and
#: *every* job downloads the same state snapshot, so the hub sees ~100 tree
#: listings in the same minute. That burst is the whole cause of the
#: `HfHubHTTPError: 429` failures that took out alfred, jobsnepal, karir_com,
#: praca_by and willhaben_at on 2026-10-30 -- not anything about those boards.
#: Retrying with exponential backoff (and jitter, so the ~100 jobs do not
#: retry in lockstep) spreads the burst out instead of failing the scrape.
_HF_MAX_ATTEMPTS = 7
_HF_INITIAL_WAIT_SECONDS = 3.0
_HF_MAX_WAIT_SECONDS = 90.0


def _is_rate_limited(exc: BaseException) -> bool:
    """True for HF 429s and transient 5xx, the failures worth retrying."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return True
    if isinstance(status, int) and 500 <= status < 600:
        return True
    text = str(exc)
    return "429" in text and "Too Many Requests" in text


def _with_hf_retry(operation: Callable[[], T], description: str) -> T:
    """Run one HuggingFace call, retrying rate limits with backoff."""
    wait = _HF_INITIAL_WAIT_SECONDS
    for attempt in range(1, _HF_MAX_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - re-raised unless rate limited
            if attempt >= _HF_MAX_ATTEMPTS or not _is_rate_limited(exc):
                raise
            pause = min(wait, _HF_MAX_WAIT_SECONDS) * (1 + random.random() * 0.4)
            logger.warning(
                "{}: HuggingFace rate limited (attempt {}/{}), retrying in {:.1f}s: {}",
                description,
                attempt,
                _HF_MAX_ATTEMPTS,
                pause,
                exc,
            )
            time.sleep(pause)
            wait *= 2
    raise AssertionError("unreachable: retry loop must return or raise")


def download_state(work: pathlib.Path) -> pathlib.Path:
    from huggingface_hub import HfApi

    token = _resolve_token()
    api = HfApi(token=token)
    names = sorted(
        n
        for n in _with_hf_retry(
            lambda: api.list_repo_files(REPO, repo_type="dataset"),
            "list_repo_files",
        )
        if n.startswith(STATE_PREFIX)
    )
    dest = work / "state"
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        local = _with_hf_retry(
            lambda name=name: api.hf_hub_download(
                repo_id=REPO, repo_type="dataset", filename=name, token=token
            ),
            f"hf_hub_download {name}",
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

        _resync_identity_sequences(conn, ordered)
    logger.info("restored {:,} reference rows", total)
    return total


def _resync_identity_sequences(conn, tables: list[tuple[str, str]]) -> list[str]:
    """Advance every identity sequence to the highest id actually loaded.

    **This is the root cause of the CI ``locations_pkey`` collisions.**

    Postgres does not move an identity sequence when a row is inserted with an
    explicit id. The restore above has to insert explicit ids -- that is the
    whole point of the snapshot, so every FK keeps lining up -- but the
    sequence is left exactly where it was. On a fresh database that means it
    still reads 1, so the first row a scraper generates collides with the row
    the snapshot already loaded at id 1.

    It stayed invisible for a long time because most sources resolve their
    locations to ids that already exist and therefore never generate a new one.
    Careers24 exposed it on its first CI run on 2026-10-16: 30 of 100 postings
    failed with ``duplicate key value violates unique constraint
    "locations_pkey"``, and the per-row savepoint swallowed each one, so the
    job still reported success while losing 30% of its rows.

    The fix has to be generic rather than a list of four known columns
    (``ref.locations``, ``ref.cities``, ``ref.regions``, ``ref.countries``),
    because any source that creates a row in any identity-bearing reference
    table hits this, and the next one will not be on the list. So every
    identity column in the loaded tables is advanced to its own ``max()``.

    ``setval`` is called with ``is_called = true`` so the next generated value
    is ``max + 1`` and not ``max`` itself.
    """
    resynced: list[str] = []
    for schema, table in tables:
        columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND is_identity = 'YES' "
                "ORDER BY ordinal_position"
            ),
            {"s": schema, "t": table},
        ).all()
        for (column,) in columns:
            ident = _quote_identifier(column)
            qualified = f"{schema}.{_quote_identifier(table)}"
            max_id = int(
                conn.execute(
                    text(f"SELECT COALESCE(MAX({ident}), 0) FROM {qualified}")
                ).scalar_one()
            )
            if max_id <= 0:
                continue
            # pg_sequence_last_value returns NULL for a sequence that has never
            # been used, which is precisely the fresh-database case this fix is
            # about. Reading it through pg_sequences instead would compare a
            # schema-qualified name against a bare sequence name and silently
            # find nothing.
            current = conn.execute(
                text("SELECT pg_sequence_last_value(pg_get_serial_sequence(:st, :c))"),
                {"st": qualified, "c": column},
            ).scalar_one()
            if current is not None and int(current) >= max_id:
                continue
            conn.execute(
                text("SELECT setval(pg_get_serial_sequence(:st, :c), :v, true)"),
                {"st": qualified, "c": column, "v": max_id},
            )
            was = current if current is not None else "unused"
            resynced.append(f"{schema}.{table}.{column} {was}->{max_id}")
    if resynced:
        logger.info("resynced {} identity sequence(s): {}", len(resynced), resynced)
    else:
        logger.info("identity sequences already at or ahead of their loaded ids")
    return resynced


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

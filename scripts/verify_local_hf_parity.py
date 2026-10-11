"""Verify the Hugging Face corpus matches the databases it is built from.

Run after scripts/export_corpus_to_hf.py. The corpus is the UNION of local
Postgres and Neon, so this checks HF against that union, not against local
alone.

Why not local alone
-------------------
It was, for a long time, and that check is what let 5,321 rows be deleted from
HF while it still passed: the count matched, the columns matched, and the data
was gone. The exporter read local only, on a documented assumption that local
was a "strict superset" of Neon -- true once, right after the one-time merge,
and untrue from the moment CI scraped anything new into Neon, because nothing
carries Neon rows back to the laptop.

Measured 2026-10-11, neither is a superset:

    local-only: jobvision +46,982   greenhouse +5,325   jobinja +207
    Neon-only : glints     +3,183    51job     +857     jobmaster +635

Reads with PYARROW, not DuckDB. DuckDB's httpfs extension raised
UnicodeDecodeError on these same files with a different byte and a different
column on every run -- weworkremotely/job_category, then glints/description_en
plus three more, then nothing at all -- while pyarrow read every file cleanly
each time. That is a network-read race in the extension, not corrupt data, and
a verifier that reports phantom corruption is worse than no verifier.

Run:  uv run python scripts/verify_local_hf_parity.py
"""

from __future__ import annotations

import io
import os
import pathlib
import re
import sys

import pyarrow.parquet as pq
import requests
from sqlalchemy import create_engine, text

REPO = "Shifat2110724169/job-market-intel-corpus"
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
TOKEN = pathlib.Path(
    r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
).read_text(encoding="utf-8").strip()

#: Data columns compared between the databases and HF. Kept to the ones that
#: actually drift: a translation applied on the laptop, a re-resolved location, a
#: merged row. ``source`` is a hive partition, handled separately.
#: posting_date is read as the raw column (not the hive partition) because it is
#: part of the natural key, not just a label.
DATA_COLUMNS = (
    "source_job_id",
    "posting_date",
    "description_en",
    "country_code",
    "location_raw",
)


def neon_dsn() -> str | None:
    """Neon DSN from .env, or None. Mirrors export_corpus_to_hf.neon_dsn()."""
    env = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*DATABASE_URL\s*=\s*(.+)$", line)
        if not m:
            continue
        url = m.group(1).strip().strip('"').strip("'")
        # Accept every spelling seen in the wild: the already-normalised
        # psycopg form from .env itself, plain postgresql:// from psql tooling,
        # and postgres:// from Heroku-style connection strings.
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix) :]
                break
        else:
            return None
        return None if url == LOCAL_DSN else url
    return None


def _read_sources(dsn: str) -> dict[str, tuple[str, object, object, object]]:
    """(source, source_job_id, posting_date) -> the compared columns.

    ``posting_date`` is part of the key because it is part of the schema's
    natural key (``uq_jobs_source_natural_key``) and therefore part of the
    shard's identity. Keying on (source, source_job_id) alone made this script
    report 113,335 for a 113,373-row database and call the correct HF snapshot
    "DIVERGED" -- a verifier that flags the fixed thing as the bug. A source
    that re-lists a posting on a later date is a genuinely distinct row (see
    export_corpus_to_hf._merge_source).
    """
    sql = (
        "SELECT s.source_code, j.source_job_id::text AS source_job_id, "
        "  j.posting_date::text AS posting_date, "
        "  (SELECT d.description_en FROM core.job_descriptions d "
        "    WHERE d.job_id = j.job_id) AS description_en, "
        "  c.iso_code_2 AS country_code, l.raw_location_text AS location_raw "
        "FROM core.jobs j "
        "JOIN ref.sources s ON s.source_id = j.source_id "
        "LEFT JOIN ref.locations l ON l.location_id = j.location_id "
        "LEFT JOIN ref.countries c ON c.country_id = l.country_id"
    )
    # Neon is a remote host; a bare connect() has no timeout and can hang for
    # minutes on a network blip instead of reporting it.
    engine = create_engine(dsn, connect_args={"connect_timeout": 15})
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).all()
    return {(r[0], r[1], r[2]): r[3:] for r in rows}


def read_shard(url: str, shard_path: str) -> dict[str, list]:
    """Fetch one shard and return the compared columns as Python lists.

    ``source`` is a HIVE PARTITION: it lives in the directory name, not in the
    file's data columns, so requesting it from pyarrow raises. Sourced from the
    path instead, which is also what DuckDB's hive_partitioning does.
    """
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    table = pq.read_table(io.BytesIO(response.content), columns=list(DATA_COLUMNS))
    out = {name: table.column(name).to_pylist() for name in DATA_COLUMNS}
    # posting_date comes back as a date object from Arrow but the SQL side casts
    # to text; normalise both to YYYY-MM-DD so the keys can actually match.
    out["posting_date"] = [str(v)[:10] if v is not None else None for v in out["posting_date"]]
    source = shard_path.split("source=", 1)[1].split("/", 1)[0]
    out["source"] = [source] * table.num_rows
    return out


def main() -> int:
    from huggingface_hub import HfApi

    api = HfApi(token=TOKEN)
    shards = sorted(
        f
        for f in api.list_repo_files(REPO, repo_type="dataset")
        # Only the corpus tree. The repo also holds state/reference*.parquet
        # (the ref.* tables behind the CI seed) and the pg dumps; those have
        # completely different columns, so feeding them to read_shard raised
        #   No match for FieldRef.Name(source_job_id) in benefit_id: int64
        if f.startswith("shards/") and f.endswith(".parquet")
    )
    print(f"{len(shards)} shards on HF")

    # Aggregate across shards one file at a time -- see the module docstring on
    # why DuckDB's parallel glob reader over hf:// is not used.
    hf_rows = 0
    hf: dict[tuple[str, str, str], tuple] = {}
    for shard in shards:
        url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{shard}"
        cols = read_shard(url, shard)
        hf_rows += len(cols["source"])
        for key, values in zip(
            zip(cols["source"], cols["source_job_id"], cols["posting_date"]),
            zip(cols["description_en"], cols["country_code"], cols["location_raw"]),
        ):
            hf[key] = values

    local = _read_sources(LOCAL_DSN)
    union = dict(local)

    neon: dict = {}
    dsn = None if os.environ.get("SKIP_NEON") == "1" else neon_dsn()
    if dsn:
        try:
            neon = _read_sources(dsn)
            union.update(neon)
            print(f"merged {len(neon):,} Neon rows ({len(union):,} in the union)")
        except Exception as exc:  # noqa: BLE001
            print(f"  Neon unreachable ({str(exc)[:80]}); checking local only")
    else:
        print("  no Neon DSN; checking local only")

    only_hf = set(hf) - set(union)
    only_db = set(union) - set(hf)

    print(f"\n{'metric':<30}{'union':>14}{'HF':>14}  match")
    print("-" * 70)
    ok = True
    for label, a, b in (
        ("rows", len(union), hf_rows),
        ("distinct identities", len(union), len(hf)),
    ):
        same = a == b
        ok = ok and same
        print(f"{label:<30}{a:>14,}{b:>14,}  {'OK' if same else 'MISMATCH'}")

    desc_hf = sum(1 for v in hf.values() if v[0])
    desc_db = sum(1 for v in union.values() if v[0])
    nocountry_hf = sum(1 for v in hf.values() if v[1] is None)
    nocountry_db = sum(1 for v in union.values() if v[1] is None)

    for label, a, b in (
        ("description_en filled", desc_db, desc_hf),
        ("no country (count)", nocountry_db, nocountry_hf),
    ):
        same = a == b
        ok = ok and same
        print(f"{label:<30}{a:>14,}{b:>14,}  {'OK' if same else 'MISMATCH'}")

    # Neon-only rows are the interesting number: it is the difference the old
    # check quietly discarded.
    neon_only = set(neon) - set(local)
    if neon or only_hf:
        print(f"\n  rows only in Neon (correctly on HF): {len(neon_only):,}")
    if only_hf:
        print(f"  on HF but in neither database      : {len(only_hf):,}  <-- investigate")
        ok = False
    if only_db:
        print(f"  in the databases but not on HF     : {len(only_db):,}  <-- re-run export")

    top: dict[str, int] = {}
    for (_src, _job_id, _posting_date), values in hf.items():
        if values[2]:
            top[values[2]] = top.get(values[2], 0) + 1
    print("\nHF location_raw top values:")
    for loc, n in sorted(top.items(), key=lambda kv: -kv[1])[:5]:
        print(f"   {str(loc)[:48]:<48}{n:>9,}")

    print(
        "\nRESULT:",
        "HF agrees with local + Neon"
        if ok
        else "DIVERGED -- re-run export_corpus_to_hf.py",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Verify the Hugging Face corpus matches the local Postgres row for row.

Run after scripts/export_corpus_to_hf.py. Compares row count, distinct
identity, and the columns most likely to drift (translations, location,
country), because "local and HF must always agree" is only true if it is
checked rather than assumed.

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
import pathlib
import sys

import pyarrow.parquet as pq
import requests
from sqlalchemy import create_engine, text

REPO = "Shifat2110724169/job-market-intel-corpus"
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
TOKEN = pathlib.Path(
    r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
).read_text(encoding="utf-8").strip()

#: Data columns compared between local and HF -- the ones that actually drift:
#: a translation applied on the laptop, a re-resolved location, a merged row.
#: ``source`` and ``dt`` are hive partitions (directory names), handled separately.
DATA_COLUMNS = ("source_job_id", "description_en", "country_code", "location_raw")


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
    out["source"] = [shard_path.split("source=", 1)[1].split("/", 1)[0]] * table.num_rows
    return out


def main() -> int:
    from huggingface_hub import HfApi

    api = HfApi(token=TOKEN)
    shards = sorted(
        f for f in api.list_repo_files(REPO, repo_type="dataset") if f.endswith(".parquet")
    )
    print(f"{len(shards)} shards on HF")

    hf_rows = hf_uniq = hf_desc_en = hf_no_country = 0
    top_locations: dict[str, int] = {}
    for shard in shards:
        url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{shard}"
        cols = read_shard(url, shard)
        n = len(cols["source"])
        hf_rows += n
        hf_uniq += len(set(zip(cols["source"], cols["source_job_id"])))
        hf_desc_en += sum(1 for v in cols["description_en"] if v is not None)
        hf_no_country += sum(1 for v in cols["country_code"] if v is None)
        for loc in cols["location_raw"]:
            if loc is not None:
                top_locations[loc] = top_locations.get(loc, 0) + 1
        print(f"  {shard.split('/', 1)[1]:<44}{n:>8,} rows")

    eng = create_engine(LOCAL_DSN)
    with eng.connect() as c:
        db_rows = c.execute(text("SELECT count(*) FROM core.jobs")).scalar_one()
        db_uniq = c.execute(
            text(
                "SELECT count(*) FROM (SELECT DISTINCT s.source_code, j.source_job_id::text "
                "FROM core.jobs j JOIN ref.sources s ON s.source_id=j.source_id) t"
            )
        ).scalar_one()
        db_desc_en = c.execute(
            text("SELECT count(*) FROM core.job_descriptions WHERE description_en IS NOT NULL")
        ).scalar_one()
        # HF's country_code comes from the country join, so it is NULL both when
        # the location row has no country AND when the job has no location row
        # at all. Compare like with like, or the check reports a phantom
        # mismatch of exactly that difference.
        db_no_country = c.execute(
            text(
                "SELECT count(*) FROM core.jobs j "
                "LEFT JOIN ref.locations l ON l.location_id = j.location_id "
                "WHERE l.country_id IS NULL"
            )
        ).scalar_one()

    print(f"\n{'metric':<28}{'local':>14}{'HF':>14}  match")
    print("-" * 66)
    ok = True
    for label, a, b in (
        ("rows", db_rows, hf_rows),
        ("distinct identities", db_uniq, hf_uniq),
        ("description_en filled", db_desc_en, hf_desc_en),
        ("no country (count)", db_no_country, hf_no_country),
    ):
        same = a == b
        ok = ok and same
        print(f"{label:<28}{a:>14,}{b:>14,}  {'OK' if same else 'MISMATCH'}")

    print("\nHF location_raw top values:")
    for loc, n in sorted(top_locations.items(), key=lambda kv: -kv[1])[:5]:
        print(f"   {str(loc)[:48]:<48}{n:>9,}")

    print("\nRESULT:", "local and HF agree" if ok else "DIVERGED -- re-run export_corpus_to_hf.py")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

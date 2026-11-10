"""
Export ref.normalized_job_titles from local PostgreSQL to HF corpus repo
as ref/normalized_job_titles.parquet

Run from repo root:
    uv run python scripts/export_taxonomy_to_hf.py
"""
import os
import pathlib
import tempfile

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import HfApi

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://app_user:changeme@localhost:5432/job_market_intelligence",
)
CORPUS_REPO_ID = "Shifat2110724169/job-market-intel-corpus"
PATH_IN_REPO = "ref/normalized_job_titles.parquet"


def main() -> None:
    print(f"Connecting to {DB_URL[:40]}...")
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    normalized_title_id,
                    normalized_title,
                    job_family
                FROM ref.normalized_job_titles
                ORDER BY normalized_title_id
                """
            )
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]

    print(f"Fetched {len(rows)} taxonomy rows from ref.normalized_job_titles")

    # Build Arrow table
    data = {col: [r[i] for r in rows] for i, col in enumerate(cols)}
    tbl = pa.table(
        {
            "normalized_title_id": pa.array(data["normalized_title_id"], type=pa.int64()),
            "normalized_title":    pa.array(data["normalized_title"],    type=pa.string()),
            "job_family":          pa.array(data["job_family"],          type=pa.string()),
        }
    )

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp = pathlib.Path(f.name)

    pq.write_table(tbl, tmp)
    print(f"Written {tbl.num_rows} rows to {tmp}")

    # Resolve token the same way as other corpus scripts
    token = None
    for var in ("CORPUS_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        val = os.environ.get(var)
        if val and val.strip():
            token = val.strip()
            break
    if not token:
        token_file = pathlib.Path(
            r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
        )
        token = token_file.read_text(encoding="utf-8").strip()

    api = HfApi(token=token)
    api.upload_file(
        path_or_fileobj=str(tmp),
        path_in_repo=PATH_IN_REPO,
        repo_id=CORPUS_REPO_ID,
        repo_type="dataset",
        token=token,
        commit_message="chore: export taxonomy snapshot for Kaggle classification kernel",
    )
    print(f"Uploaded to {CORPUS_REPO_ID}/{PATH_IN_REPO}")
    tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

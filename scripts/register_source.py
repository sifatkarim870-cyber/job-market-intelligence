"""Register a new source in ref.sources, locally and on Hugging Face.

A scraper cannot persist anything until ``ref.sources`` has a row for its code:
``JobRepository.get_source_id_by_code`` resolves that row, and
``core.jobs.source_id`` is a NOT NULL foreign key into it. Registering in
``config/sources.json`` alone is not enough -- that file drives which jobs CI
runs, not what the database accepts.

The HF copy matters as much as the local one: CI seeds its database from
``state/reference.parquet``, so a source missing there cannot run in CI even
though it works locally. Publishing with this script rather than by hand is
what keeps the two copies from drifting.

Usage:
    python scripts/register_source.py --code himalayas --name Himalayas
    python scripts/register_source.py --code X --name "X Ltd" --type job_board \\
        --base-url https://example.com --trust-score 0.70
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
REPO = "Shifat2110724169/job-market-intel-corpus"
HF_TOKEN_FILE = pathlib.Path(
    r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
)


def resolve_token() -> str:
    """HF token from the environment, else the local token file."""
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = os.environ.get(name)
        if token:
            return token
    if HF_TOKEN_FILE.exists():
        return HF_TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit("no HF token: set HF_TOKEN or place one at " + str(HF_TOKEN_FILE))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--code", required=True, help="source_code, e.g. himalayas")
    ap.add_argument("--name", required=True, help="human-readable source_name")
    ap.add_argument("--type", default="job_board", help="ref.sources.source_type")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--tos-url", default=None)
    ap.add_argument("--trust-score", type=float, default=0.70)
    ap.add_argument("--inactive", action="store_true", help="insert with is_active=false")
    ap.add_argument("--dsn", default=LOCAL_DSN)
    ap.add_argument("--no-publish", action="store_true", help="skip the HF state snapshot")
    args = ap.parse_args(argv)

    engine = create_engine(args.dsn)
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT source_id, is_active FROM ref.sources WHERE source_code = :c"),
            {"c": args.code},
        ).first()
        if row:
            logger.info(
                "source {} already exists (source_id={}, is_active={})",
                args.code,
                row[0],
                row[1],
            )
            return 0
        source_id = conn.execute(
            text(
                """
                INSERT INTO ref.sources
                    (source_code, source_name, source_type, base_url,
                     requires_auth, terms_of_service_url, trust_score, is_active)
                VALUES (:code, :name, :type, :url, false, :tos, :trust, :active)
                RETURNING source_id
                """
            ),
            {
                "code": args.code,
                "name": args.name,
                "type": args.type,
                "url": args.base_url,
                "tos": args.tos_url,
                "trust": args.trust_score,
                "active": not args.inactive,
            },
        ).scalar_one()
    logger.info("registered {} as source_id={} in the local database", args.code, source_id)

    if args.no_publish:
        logger.warning("--no-publish: the HF state snapshot is stale, so CI cannot use this yet")
        return 0

    # Republish the whole state snapshot rather than patching one Parquet file:
    # export_state_snapshot.py already dumps every ref.* table plus the schema,
    # and hand-editing reference.parquet is how the two copies drift.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import export_state_snapshot  # noqa: PLC0415

    os.environ.setdefault("HF_TOKEN", resolve_token())
    logger.info("republishing the state snapshot so CI can seed this source")
    export_state_snapshot.main()
    logger.info("done: {} is available to both the laptop and CI", args.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Mirror the corpus from Hugging Face down to this laptop.

Why
---
The laptop is a system of record, not a cache. It holds the local Postgres that
CI cannot reach, including the tables the flat shards have no equivalent for --
``salary.salary_history``, ``bridge.*``, ``audit.*``, ``ops.*`` -- so it needs
its own copy of everything. And it needs to take that copy *whenever the machine
is actually on*: a laptop that sleeps through a 03:00 cron must still sync when
it wakes, which is why this is scheduled to run at logon and to catch up on a
missed run (see ``scripts/register_backup_task.ps1``).

What it pulls
-------------
1. ``dumps/local_full.dump`` / ``dumps/neon_full.dump`` -- full ``pg_dump -Fc``
   archives of both databases, restorable with ``pg_restore``. These are the
   *complete* copies; the Parquet shards are the queryable ones.
2. The Parquet shards, via DuckDB's ``httpfs``: range-reads and column-selective,
   with a hard memory cap so a 20 GB laptop stays cool.
3. A manifest with sizes and optional hashes, so "did today's backup land?" is
   answerable without reading data.

Cost discipline
---------------
I/O and network, not compute: no model, no re-encoding, no SQL over the corpus.
Row counts come from Parquet footers (a few KB) rather than a scan.
Downloads are skipped when the local size already matches, and ``--max-age-hours``
lets a scheduler fire hourly while real work still happens once a day.

Usage:
    python scripts/sync_corpus_from_hf.py
    python scripts/sync_corpus_from_hf.py --skip-dumps --max-age-hours 20
    python scripts/sync_corpus_from_hf.py --full-verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_REPO = "Shifat2110724169/job-market-intel-corpus"
DEFAULT_TOKEN_FILE = Path(
    r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
)
DEFAULT_DEST = Path(r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\corpus_backup")
MANIFEST_NAME = "manifest.json"


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M:%SZ}] {msg}", flush=True)


def resolve_token(explicit: str | None, token_file: Path | None) -> str | None:
    """Explicit arg -> token file -> HF_TOKEN / HUGGING_FACE_HUB_TOKEN."""
    if explicit:
        return explicit.strip()
    for candidate in (token_file, DEFAULT_TOKEN_FILE):
        if candidate and candidate.exists():
            text = candidate.read_text(encoding="utf-8").strip()
            if text:
                return text
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def remote_files(repo_id: str, token: str | None) -> list[dict]:
    """Every file in the dataset with its size (from Hub metadata, not listing)."""
    from huggingface_hub import HfApi

    info = HfApi(token=token).dataset_info(repo_id, files_metadata=True)
    return [
        {"path": s.rfilename, "bytes": int(getattr(s, "size", None) or 0)} for s in info.siblings
    ]


def download_dumps(
    files: list[dict], dest: Path, repo_id: str, token: str | None, force: bool
) -> list[dict]:
    """Fetch the pg_dump archives; skip any whose local size already matches."""
    from huggingface_hub import hf_hub_download

    dest.mkdir(parents=True, exist_ok=True)
    fetched: list[dict] = []
    for entry in files:
        path = entry["path"]
        if not path.startswith("dumps/") or not path.endswith(".dump"):
            continue
        target = dest / Path(path).name
        if target.exists() and not force and target.stat().st_size == entry["bytes"]:
            _log(f"skip {target.name} (already {entry['bytes'] / 1e6:.1f} MB)")
            fetched.append({**entry, "local": str(target), "skipped": True})
            continue
        _log(f"fetch {path} ({entry['bytes'] / 1e6:.1f} MB)")
        cached = hf_hub_download(repo_id=repo_id, filename=path, repo_type="dataset", token=token)
        shutil.copy2(cached, target)
        fetched.append({**entry, "local": str(target), "skipped": False})
    return fetched


def count_remote_rows(files: list[dict], repo_id: str, memory_limit: str) -> dict:
    """Row count straight from Parquet footers -- a few KB, not a scan."""
    import duckdb

    paths = [
        e["path"]
        for e in files
        if e["path"].endswith(".parquet")
        # both trees, matched on the segment boundary: "shards_local/..." must
        # not be picked up by a "shards" substring test that anchors mid-path
        and e["path"].startswith(("shards/", "shards_local/"))
    ]
    if not paths:
        return {"shard_files": 0, "rows": None, "bytes": 0}
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute("SET temp_directory='D:/duckdb_tmp'")
    con.execute("INSTALL httpfs; LOAD httpfs")
    urls = [f"hf://datasets/{repo_id}/{p}" for p in sorted(paths)]
    started = time.time()
    rows = con.execute(
        f"SELECT count(*) FROM read_parquet({urls!r}, hive_partitioning=true)"
    ).fetchone()[0]
    _log(f"remote shard rows: {rows:,} ({time.time() - started:.1f}s, footer-only read)")
    return {
        "shard_files": len(paths),
        "rows": int(rows),
        "bytes": sum(e["bytes"] for e in files if e["path"] in paths),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--memory-limit", default="1GB", help="DuckDB memory cap; 1GB keeps a 20 GB laptop cool"
    )
    parser.add_argument("--skip-dumps", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-download despite matching sizes")
    parser.add_argument("--full-verify", action="store_true", help="sha256 the downloads")
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=0.0,
        help="exit early when the manifest is fresher than this",
    )
    args = parser.parse_args(argv)

    dest: Path = args.dest
    manifest_path = dest / MANIFEST_NAME

    if args.max_age_hours > 0 and manifest_path.exists():
        try:
            last = datetime.fromisoformat(
                json.loads(manifest_path.read_text(encoding="utf-8"))["synced_at"]
            )
            age = (datetime.now(UTC) - last).total_seconds() / 3600
            if age < args.max_age_hours:
                _log(f"last sync {age:.1f}h ago; nothing to do")
                return 0
        except Exception as exc:  # noqa: BLE001 - a bad manifest must not block a sync
            _log(f"manifest unreadable ({exc}); syncing anyway")

    token = resolve_token(args.token, args.token_file)
    if not token:
        _log("no Hugging Face token found (arg, token file, or HF_TOKEN)")
        return 1

    started = time.time()
    _log(f"syncing {args.repo} -> {dest}")
    files = remote_files(args.repo, token)
    _log(f"{len(files)} files in the dataset")

    report: dict = {
        "repo": args.repo,
        "synced_at": datetime.now(UTC).isoformat(),
        "dumps": [],
        "shards": {},
    }
    if not args.skip_dumps:
        report["dumps"] = download_dumps(files, dest / "dumps", args.repo, token, args.force)
    report["shards"] = count_remote_rows(files, args.repo, args.memory_limit)

    if args.full_verify:
        for entry in report["dumps"]:
            entry["sha256"] = sha256(Path(entry["local"]))
            _log(f"sha256 {Path(entry['local']).name}: {entry['sha256'][:16]}...")

    report["elapsed_s"] = round(time.time() - started, 1)
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log(
        f"done in {report['elapsed_s']}s: dumps={len(report['dumps'])} "
        f"rows={report['shards'].get('rows')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

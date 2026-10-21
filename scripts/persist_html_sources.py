#!/usr/bin/env python
"""Persist every HTML scraper source that passed the dry-run sweep.

Reads reports/html_scraper_test_results.json, and for each OK source runs the
pipeline with store_db=True, then reports how many rows that source now has.

Usage:
    uv run python scripts/persist_html_sources.py            # all OK sources
    uv run python scripts/persist_html_sources.py --only ams_at
    uv run python scripts/persist_html_sources.py --max-jobs 40 --resume
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import text

from job_market_intel.db.session import get_session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNNER = PROJECT_ROOT / "scripts" / "run_html_scraper.py"
RESULTS = PROJECT_ROOT / "reports" / "html_scraper_test_results.json"
OUT = PROJECT_ROOT / "reports" / "html_scraper_persist_results.json"


def row_counts() -> dict[str, int]:
    with get_session() as s:
        rows = s.execute(
            text(
                "SELECT s.source_code, count(j.job_id) "
                "FROM ref.sources s LEFT JOIN core.jobs j ON j.source_id = s.source_id "
                "GROUP BY s.source_code"
            )
        ).all()
    return {code: int(n) for code, n in rows}


def persist(code: str, max_jobs: int, timeout: int) -> dict:
    started = time.time()
    cmd = [
        sys.executable,
        str(RUNNER),
        "--source-code",
        code,
        "--max-jobs",
        str(max_jobs),
        "--max-pages",
        "3",
        "--delay",
        "0.2",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        fields = {}
        for line in out.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                if key in {
                    "Postings fetched",
                    "Parsed",
                    "Cleaned",
                    "Inserted",
                    "Updated",
                    "Unchanged",
                    "Failed to persist",
                }:
                    try:
                        fields[key] = int(val.strip())
                    except ValueError:
                        pass
        ok = proc.returncode == 0
        detail = "" if ok else out.splitlines()[-1][:200] if out.splitlines() else ""
    except subprocess.TimeoutExpired:
        fields = {}
        ok = False
        detail = f"exceeded {timeout}s"
    return {
        "code": code,
        "ok": ok,
        "inserted": fields.get("Inserted", 0),
        "updated": fields.get("Updated", 0),
        "unchanged": fields.get("Unchanged", 0),
        "failed": fields.get("Failed to persist", 0),
        "parsed": fields.get("Parsed", 0),
        "seconds": round(time.time() - started, 1),
        "detail": detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--max-jobs", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if args.only:
        codes = args.only
    else:
        if not RESULTS.exists():
            print(f"missing {RESULTS}; run scripts/test_all_html_scrapers.py first")
            return 1
        results = json.loads(RESULTS.read_text(encoding="utf-8"))
        codes = [r["code"] for r in results if r["status"] == "OK"]

    done: dict[str, dict] = {}
    if args.resume and OUT.exists():
        for row in json.loads(OUT.read_text(encoding="utf-8")):
            done[row["code"]] = row
    pending = [c for c in codes if c not in done]

    print(f"{len(codes)} OK source(s); {len(pending)} to persist.", flush=True)
    out_rows: list[dict] = [done[c] for c in codes if c in done]
    before_counts = row_counts()

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(persist, code, args.max_jobs, args.timeout): code for code in pending
        }
        for i, fut in enumerate(futures, start=1):
            res = fut.result()
            out_rows.append(res)
            print(
                f"[{i}/{len(pending)}] {res['code']}: inserted={res['inserted']} "
                f"parsed={res['parsed']} ({res['seconds']}s)"
                + (f" ERROR {res['detail']}" if res["detail"] else ""),
                flush=True,
            )
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(out_rows, indent=2), encoding="utf-8")

    after_counts = row_counts()
    for row in out_rows:
        row["rows_before"] = before_counts.get(row["code"], 0)
        row["rows_after"] = after_counts.get(row["code"], 0)

    OUT.write_text(json.dumps(out_rows, indent=2), encoding="utf-8")
    gained = sum(r["rows_after"] - r["rows_before"] for r in out_rows)
    total = sum(r["rows_after"] for r in out_rows)
    print(f"\nnet new rows: {gained}; rows in these sources now: {total}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

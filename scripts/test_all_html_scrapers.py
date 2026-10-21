#!/usr/bin/env python
"""Test every registered HTML scraper site config in one pass.

Each site is run in its own subprocess (so a hang or crash cannot take down
the batch) with a hard wall-clock timeout. Results are written to a JSON file
plus a human-readable Markdown report.

Usage:
    uv run python scripts/test_all_html_scrapers.py
    uv run python scripts/test_all_html_scrapers.py --workers 8 --max-jobs 2
    uv run python scripts/test_all_html_scrapers.py --only skilljobs --only pracecz
    uv run python scripts/test_all_html_scrapers.py --resume
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "run_html_scraper.py"
REPORT_DIR = PROJECT_ROOT / "reports"

FETCHED_RE = re.compile(r"Postings fetched:\s*(\d+)")
PARSED_RE = re.compile(r"Parsed:\s*(\d+)")
CLEANED_RE = re.compile(r"Cleaned:\s*(\d+)")

BLOCK_MARKERS = (
    "403 Forbidden",
    "403 Client Error",
    "429 Client Error",
    "Cloudflare",
    "cf-browser-verification",
    "Just a moment",
    "Attention Required",
    "Access Denied",
    "captcha",
)
NO_LINK_MARKERS = (
    "no postings found",
    "HtmlScraperResponseError",
)
DNS_MARKERS = (
    "Name or service not known",
    "getaddrinfo failed",
    "nodename nor servname",
    "Failed to resolve",
    "No address associated with hostname",
)


def discover_sites() -> list[str]:
    """Every JSON config shipped with the framework."""
    sites_dir = PROJECT_ROOT / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
    return sorted(p.stem for p in sites_dir.glob("*.json"))


def classify(output: str, fetched: int, parsed: int, returncode: int) -> str:
    if parsed > 0:
        return "OK"
    if any(m in output for m in DNS_MARKERS):
        return "DNS_FAIL"
    if any(m in output for m in BLOCK_MARKERS):
        return "BLOCKED"
    if any(m in output for m in NO_LINK_MARKERS):
        return "NO_LINKS"
    if fetched > 0:
        return "PARSE_FAIL"
    if "FileNotFoundError" in output and "Site config not found" in output:
        return "NO_CONFIG"
    if returncode != 0:
        return "ERROR"
    return "EMPTY"


def last_error_line(output: str) -> str:
    """Best-effort single-line reason from a noisy traceback."""
    for marker in BLOCK_MARKERS + DNS_MARKERS + NO_LINK_MARKERS:
        if marker in output:
            return marker
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith(("FileNotFoundError", "RuntimeError", "ValueError")):
            return line[:200]
    for line in reversed(lines):
        if "Error" in line or "Exception" in line:
            return line[:200]
    return lines[-1][:200] if lines else ""


def run_one(code: str, max_jobs: int, max_pages: int, timeout: int) -> dict:
    started = time.time()
    cmd = [
        sys.executable,
        str(RUNNER),
        "--source-code",
        code,
        "--no-db",
        "--max-jobs",
        str(max_jobs),
        "--max-pages",
        str(max_pages),
        "--delay",
        "0",
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
        output = (proc.stdout or "") + (proc.stderr or "")
        fetched = int(m.group(1)) if (m := FETCHED_RE.search(output)) else 0
        parsed = int(m.group(1)) if (m := PARSED_RE.search(output)) else 0
        status = classify(output, fetched, parsed, proc.returncode)
        detail = "" if status == "OK" else last_error_line(output)
    except subprocess.TimeoutExpired:
        fetched = parsed = 0
        status = "TIMEOUT"
        detail = f"exceeded {timeout}s"
    elapsed = round(time.time() - started, 1)
    return {
        "code": code,
        "status": status,
        "fetched": fetched,
        "parsed": parsed,
        "seconds": elapsed,
        "detail": detail,
    }


def write_report(results: list[dict], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    order = [
        "OK",
        "PARSE_FAIL",
        "NO_LINKS",
        "BLOCKED",
        "DNS_FAIL",
        "TIMEOUT",
        "ERROR",
        "NO_CONFIG",
        "EMPTY",
    ]
    buckets: dict[str, list[dict]] = {k: [] for k in order}
    for r in results:
        buckets.setdefault(r["status"], []).append(r)

    lines = [
        "# HTML scraper sweep",
        "",
        f"Total configs tested: **{len(results)}**",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    for key in order:
        if buckets.get(key):
            lines.append(f"| {key} | {len(buckets[key])} |")
    lines.append("")

    for key in order:
        rows = buckets.get(key) or []
        if not rows:
            continue
        lines.append(f"## {key} ({len(rows)})")
        lines.append("")
        if key == "OK":
            lines.append("| Source | Fetched | Parsed | Seconds |")
            lines.append("| --- | --- | --- | --- |")
            for r in sorted(rows, key=lambda x: (-x["parsed"], x["code"])):
                lines.append(f"| {r['code']} | {r['fetched']} | {r['parsed']} | {r['seconds']} |")
        else:
            lines.append("| Source | Seconds | Reason |")
            lines.append("| --- | --- | --- |")
            for r in sorted(rows, key=lambda x: x["code"]):
                reason = (r["detail"] or "").replace("|", "/")[:160]
                lines.append(f"| {r['code']} | {r['seconds']} | {reason} |")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Test every HTML scraper site config.")
    ap.add_argument("--max-jobs", type=int, default=2, help="Postings per site.")
    ap.add_argument("--max-pages", type=int, default=2, help="Listing pages per site.")
    ap.add_argument("--timeout", type=int, default=90, help="Wall clock per site (s).")
    ap.add_argument("--workers", type=int, default=6, help="Parallel sites.")
    ap.add_argument("--only", action="append", default=None, help="Restrict to code(s).")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Reuse earlier results and only test sites with no result yet.",
    )
    ap.add_argument(
        "--json-out",
        default=str(REPORT_DIR / "html_scraper_test_results.json"),
    )
    ap.add_argument(
        "--md-out",
        default=str(REPORT_DIR / "html_scraper_test_results.md"),
    )
    args = ap.parse_args()

    json_path = Path(args.json_out)
    sites = args.only or discover_sites()

    previous: dict[str, dict] = {}
    if args.resume and json_path.exists():
        for row in json.loads(json_path.read_text(encoding="utf-8")):
            previous[row["code"]] = row

    pending = [s for s in sites if s not in previous]
    print(f"{len(sites)} config(s); {len(pending)} to test.", flush=True)

    results: list[dict] = [previous[s] for s in sites if s in previous]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_one, code, args.max_jobs, args.max_pages, args.timeout): code
            for code in pending
        }
        for i, fut in enumerate(futures, start=1):
            row = fut.result()
            futures[fut]
            results.append(row)
            print(
                f"[{i}/{len(pending)}] {row['code']}: {row['status']} "
                f"(fetched={row['fetched']}, parsed={row['parsed']}, {row['seconds']}s)"
                + (f" - {row['detail']}" if row["detail"] else ""),
                flush=True,
            )

    order = {code: i for i, code in enumerate(sites)}
    results.sort(key=lambda r: order.get(r["code"], 9999))
    write_report(results, json_path, Path(args.md_out))

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\n" + "=" * 60)
    for key, val in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{key:12} {val}")
    print("=" * 60)
    print(f"JSON: {json_path}")
    print(f"Report: {args.md_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

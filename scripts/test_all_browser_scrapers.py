#!/usr/bin/env python
"""Test every registered browser (Selenium) scraper site config in one pass.

Each site runs in its own subprocess -- a browser that hangs or crashes must
not take the batch down -- with a hard wall-clock timeout. Results go to a
JSON file plus a Markdown report.

A browser sweep has one verdict the HTML sweep did not need: CHALLENGE. A
rendered page that says "verify you are human" is the board refusing this
client, which is a different problem from "the page had no job links" and
worth counting separately.

Usage:
    uv run python scripts/test_all_browser_scrapers.py
    uv run python scripts/test_all_browser_scrapers.py --workers 2 --max-jobs 2
    uv run python scripts/test_all_browser_scrapers.py --only ethiojobs
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
RUNNER = SCRIPT_DIR / "run_browser_scraper.py"
REPORT_DIR = PROJECT_ROOT / "reports"
SITES_DIR = PROJECT_ROOT / "src" / "job_market_intel" / "scrapers" / "browser_scraper" / "sites"

FETCHED_RE = re.compile(r"Postings fetched:\s*(\d+)")
PARSED_RE = re.compile(r"Parsed:\s*(\d+)")
CLEANED_RE = re.compile(r"Cleaned:\s*(\d+)")

CHALLENGE_MARKERS = (
    "bot challenge",
    "BrowserChallengeError",
    "verify you are human",
    "just a moment",
    "pardon our interruption",
    "安全验证",
)
BLOCK_MARKERS = (
    "403 Forbidden",
    "403 Client Error",
    "429 Client Error",
    "Too Many Requests",
    "Access Denied",
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
    "ERR_NAME_NOT_RESOLVED",
)
SESSION_MARKERS = (
    "SessionNotCreated",
    "failed to start",
    "chrome session",
    "Message: unknown error",
    "WebDriverException",
)

ORDER = [
    "OK",
    "PARSE_FAIL",
    "CHALLENGE",
    "NO_LINKS",
    "BLOCKED",
    "SESSION_FAIL",
    "DNS_FAIL",
    "TIMEOUT",
    "ERROR",
    "NO_CONFIG",
    "EMPTY",
]


def discover_sites() -> list[str]:
    """Every JSON config shipped with the browser framework."""
    if not SITES_DIR.exists():
        return []
    return sorted(path.stem for path in SITES_DIR.glob("*.json"))


def classify(output: str, fetched: int, parsed: int, returncode: int) -> str:
    if parsed > 0:
        return "OK"
    if any(marker in output for marker in CHALLENGE_MARKERS):
        return "CHALLENGE"
    if any(marker in output for marker in DNS_MARKERS):
        return "DNS_FAIL"
    if any(marker in output for marker in BLOCK_MARKERS):
        return "BLOCKED"
    if any(marker in output for marker in SESSION_MARKERS):
        return "SESSION_FAIL"
    if any(marker in output for marker in NO_LINK_MARKERS):
        return "NO_LINKS"
    if "FileNotFoundError" in output and "site config not found" in output.lower():
        return "NO_CONFIG"
    if fetched > 0:
        return "PARSE_FAIL"
    if returncode != 0:
        return "ERROR"
    return "EMPTY"


def last_error_line(output: str) -> str:
    """Best-effort single-line reason from a noisy log."""
    for marker in CHALLENGE_MARKERS + DNS_MARKERS + BLOCK_MARKERS + SESSION_MARKERS:
        if marker in output:
            return marker
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(
            ("BrowserChallengeError", "BrowserFetchError", "FileNotFoundError", "RuntimeError")
        ):
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
    return {
        "code": code,
        "status": status,
        "fetched": fetched,
        "parsed": parsed,
        "seconds": round(time.time() - started, 1),
        "detail": detail,
    }


def write_report(results: list[dict], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    buckets: dict[str, list[dict]] = {key: [] for key in ORDER}
    for row in results:
        buckets.setdefault(row["status"], []).append(row)

    lines = [
        "# Browser (Selenium) scraper sweep",
        "",
        f"Total configs tested: **{len(results)}**",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    for key in ORDER:
        if buckets.get(key):
            lines.append(f"| {key} | {len(buckets[key])} |")
    lines.append("")

    for key in ORDER:
        rows = buckets.get(key) or []
        if not rows:
            continue
        lines.append(f"## {key} ({len(rows)})")
        lines.append("")
        if key == "OK":
            lines.append("| Source | Fetched | Parsed | Seconds |")
            lines.append("| --- | --- | --- | --- |")
            for row in sorted(rows, key=lambda x: (-x["parsed"], x["code"])):
                lines.append(
                    f"| {row['code']} | {row['fetched']} | {row['parsed']} | {row['seconds']} |"
                )
        else:
            lines.append("| Source | Seconds | Reason |")
            lines.append("| --- | --- | --- |")
            for row in sorted(rows, key=lambda x: x["code"]):
                reason = (row["detail"] or "").replace("|", "/")[:160]
                lines.append(f"| {row['code']} | {row['seconds']} | {reason} |")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Test every browser scraper site config.")
    ap.add_argument("--max-jobs", type=int, default=2, help="Postings per site.")
    ap.add_argument("--max-pages", type=int, default=1, help="Listing pages per site.")
    ap.add_argument("--timeout", type=int, default=300, help="Wall clock per site (s).")
    ap.add_argument("--workers", type=int, default=2, help="Parallel browsers.")
    ap.add_argument("--only", action="append", default=None, help="Restrict to code(s).")
    ap.add_argument("--json-out", default=str(REPORT_DIR / "browser_scraper_test_results.json"))
    ap.add_argument("--md-out", default=str(REPORT_DIR / "browser_scraper_test_results.md"))
    args = ap.parse_args()

    json_path = Path(args.json_out)
    sites = args.only or discover_sites()
    print(f"{len(sites)} config(s); {len(sites)} to test.", flush=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(run_one, code, args.max_jobs, args.max_pages, args.timeout): code
            for code in sites
        }
        for index, future in enumerate(futures, start=1):
            row = future.result()
            results.append(row)
            print(
                f"[{index}/{len(sites)}] {row['code']}: {row['status']} "
                f"(fetched={row['fetched']}, parsed={row['parsed']}, {row['seconds']}s)"
                + (f" - {row['detail'][:120]}" if row["detail"] else ""),
                flush=True,
            )

    write_report(results, json_path, Path(args.md_out))

    print("\n" + "=" * 60)
    for key in ORDER:
        count = sum(1 for row in results if row["status"] == key)
        if count:
            print(f"{key:14} {count}")
    print("=" * 60)
    print(f"JSON: {json_path}")
    print(f"Report: {Path(args.md_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

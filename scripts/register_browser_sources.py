#!/usr/bin/env python
"""Move a source code from the HTML group to the browser (Selenium) group.

A board that renders its listings client-side cannot be scraped with
``requests``: the server sends an empty shell and the job list only exists
after the page's JavaScript runs. The browser framework reads the rendered
page instead.

Moving a code means one owner per code. The old HTML site config is deleted,
the registry entry switches to the browser runner and the browser group, and
the two frameworks can no longer store the same posting twice under one
``source_id``.

Each moved source is committed on its own with ``--commit-each``.

Usage:
    uv run python scripts/register_browser_sources.py --dry-run
    uv run python scripts/register_browser_sources.py --commit-each
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "config" / "sources.json"
HTML_SITES = ROOT / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
BROWSER_SITES = ROOT / "src" / "job_market_intel" / "scrapers" / "browser_scraper" / "sites"
RESULTS = ROOT / "reports" / "browser_scraper_test_results.json"

BROWSER_SCRIPT = "scripts/run_browser_scraper.py"

#: code -> why it needs a browser
MOVES: dict[str, str] = {
    "ethiojobs": (
        "client-side rendered: plain HTTP returns the shell, the job list only "
        "exists after the page's JavaScript runs"
    ),
    "bumeran_com_ar": "client-side rendered: the job list is built by JavaScript",
    "bumeran_com_pe": "client-side rendered: the job list is built by JavaScript",
    "minajobs": "client-side rendered: the job list is built by JavaScript",
    "ngcareers_com": ("client-side rendered: jobberman.com returns an empty shell to plain HTTP"),
    "keejob_com": "client-side rendered: the job list is built by JavaScript",
    "careercenter_am": "client-side rendered: the job list is built by JavaScript",
    "arbeidsplassen_nav_no": ("client-side rendered: the vacancy list is built by JavaScript"),
}


def load_results() -> dict[str, dict]:
    if not RESULTS.exists():
        return {}
    return {row["code"]: row for row in json.loads(RESULTS.read_text(encoding="utf-8"))}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8"
    )


def write_sources(data: dict) -> None:
    SOURCES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def apply_move(data: dict, code: str, reason: str, results: dict[str, dict]) -> str:
    """Update one entry in place. Returns the note that was written."""
    result = results.get(code) or {}
    parsed = result.get("parsed", 0)
    note = (
        f"Browser-scraped (Selenium, undetected Chrome): {reason}. "
        f"Verified {date.today().isoformat()}: {parsed} posting(s) parsed over "
        f"{result.get('fetched', 0)} rendered page(s)."
    )
    for entry in data["sources"]:
        if entry.get("code") != code:
            continue
        entry["group"] = "browser"
        entry["script"] = BROWSER_SCRIPT
        entry["enabled"] = True
        # A browser run is minutes, not seconds: Chrome startup, a rendered
        # listing, then a rendered page per posting.
        entry["timeout"] = 45
        base = entry.get("notes", "").rstrip()
        if note not in base:
            entry["notes"] = f"{base} {note}".strip()
    return note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit-each", action="store_true")
    ap.add_argument("--code", action="append", default=None, help="Restrict to code(s).")
    args = ap.parse_args()

    results = load_results()
    codes = [code for code in (args.code or MOVES) if code in MOVES]
    if not codes:
        print("nothing to move")
        return 1

    data = json.loads(SOURCES.read_text(encoding="utf-8"))

    if args.dry_run:
        for code in codes:
            note = apply_move(data, code, MOVES[code], results)
            print(f"MOVE {code}: {note}")
        return 0

    for code in codes:
        preview = json.loads(SOURCES.read_text(encoding="utf-8"))
        note = apply_move(preview, code, MOVES[code], results)
        write_sources(preview)
        # The accumulated state has to follow the commits: the file written
        # after the loop must be the one the last commit contains, not the
        # state the loop started from.
        data = preview

        old_html_config = HTML_SITES / f"{code}.json"
        had_html_config = old_html_config.exists()
        if had_html_config:
            old_html_config.unlink()

        if args.commit_each:
            git("add", "config/sources.json")
            # One source per commit: only this source's own config, so the
            # history reads as one commit per board.
            git("add", str((BROWSER_SITES / f"{code}.json").relative_to(ROOT)).replace("\\", "/"))
            if had_html_config:
                git(
                    "add",
                    "-A",
                    str(old_html_config.relative_to(ROOT)).replace("\\", "/"),
                )
            if not git("diff", "--cached", "--name-only").stdout.strip():
                print(f"no change {code}")
                continue
            message = (
                f"Scrape {code} with a browser instead of plain HTTP\n\n"
                f"{note}\n\n"
                f"The site's own listing is rendered by JavaScript, so the HTML "
                f"framework received a shell with no job links. The browser "
                f"framework renders it and reads the result."
            )
            result = git("commit", "-m", message)
            if result.returncode != 0:
                print(result.stdout, result.stderr)
                return 1
            print(f"committed {code}")
        else:
            print(f"moved {code}")

    write_sources(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())

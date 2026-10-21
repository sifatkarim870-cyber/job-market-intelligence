#!/usr/bin/env python
"""Sync config/sources.json with what the live sweep actually proved.

- OK sources stay enabled and get a "Verified" note with their persisted counts.
- Everything else is disabled with the measured reason, so the CI matrix stops
  running scrapers that are known not to work.
- --commit-each commits each verified source on its own.

Usage:
    uv run python scripts/update_html_source_status.py --dry-run
    uv run python scripts/update_html_source_status.py --commit-each
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
VERIFIED = ROOT / "config" / "html_verified_sources.json"
TEST_RESULTS = ROOT / "reports" / "html_scraper_test_results.json"
PERSIST_RESULTS = ROOT / "reports" / "html_scraper_persist_results.json"
AUDIT_RESULTS = ROOT / "reports" / "html_scraper_audit_results.json"

REASONS = {
    "NO_LINKS": "listing returned no job links with plain HTTP (client-rendered or wrong path)",
    "BLOCKED": "listing refused the request (HTTP 403/WAF)",
    "TIMEOUT": "listing or detail pages exceeded the test timeout",
    "EMPTY": "listing request failed (server error, TLS, or timeout)",
    "PARSE_FAIL": "pages fetched but no posting could be parsed",
    "ERROR": "scraper raised an unexpected error",
    "NO_CONFIG": "no site config",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8"
    )


def write_sources(data: dict) -> None:
    SOURCES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verified_note(today: str, result: dict, row: dict) -> str:
    return (
        f"Verified {today}: {result['parsed']} posting(s) parsed over "
        f"{result['fetched']} fetched; {row.get('inserted', 0)} row(s) inserted, "
        f"{row.get('rows_after', 0)} row(s) now stored."
    )


def disabled_note(today: str, result: dict, audit: dict) -> str:
    reason = REASONS.get(result["status"], result["status"].lower())
    detail = (result.get("detail") or "").strip()
    if result["status"] == "OK":
        kept = int(audit.get("kept", 0))
        first = audit.get("first_reason") or "no job posting among the rows stored"
        reason = (
            f"parsed records but the audit kept {kept} posting(s); examples rejected as {first}"
        )
        detail = ""
    if detail:
        reason = f"{reason}; observed: {detail[:120]}"
    return f"Disabled {today} after live sweep: {reason}."


def apply_status(
    data: dict,
    tests: dict[str, dict],
    persisted: dict[str, dict],
    audit: dict[str, dict],
    verified: set[str] | None,
    today: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Rewrite enabled/notes in place. Returns (verified, disabled) code lists.

    A sweep that parsed records is not enough: the first sweep "parsed" 578
    rows that turned out to be navigation links. A source is enabled only when
    it is on the hand-checked list in ``config/html_verified_sources.json``
    (each entry records the URL shape that was inspected) *and* the audit found
    genuine postings among the rows it stored.
    """
    verified_out: list[tuple[str, str]] = []
    disabled: list[str] = []
    for entry in data["sources"]:
        code = entry.get("code")
        result = tests.get(code)
        if not result:
            continue
        notes = entry.get("notes", "").rstrip()
        kept = int((audit.get(code) or {}).get("kept", 0))
        allowed = verified is None or code in verified
        if result["status"] == "OK" and allowed and kept > 0:
            note = verified_note(today, result, persisted.get(code, {}))
            entry["enabled"] = True
            verified_out.append((code, note))
        else:
            note = disabled_note(today, result, audit.get(code) or {})
            entry["enabled"] = False
            disabled.append(code)
        if note not in notes:
            entry["notes"] = f"{notes} {note}".strip()
    return verified_out, disabled


def commit_for(code: str, note: str) -> bool:
    git("add", "config/sources.json")
    if not git("diff", "--cached", "--name-only").stdout.strip():
        return False
    res = git("commit", "-m", f"Enable {code} after live HTML sweep\n\n{note}")
    if res.returncode != 0:
        print(res.stdout, res.stderr)
        return False
    return True


def commit_each(verified: list[tuple[str, str]], data: dict) -> None:
    """One commit per verified source, each touching only its own entry."""
    for code, note in verified:
        preview = json.loads(SOURCES.read_text(encoding="utf-8"))
        for entry in preview["sources"]:
            if entry.get("code") == code:
                entry["enabled"] = True
                base = entry.get("notes", "").rstrip()
                if note not in base:
                    entry["notes"] = f"{base} {note}".strip()
        write_sources(preview)
        done = commit_for(code, note)
        print(f"{'committed' if done else 'no change'} {code}")
    write_sources(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit-each", action="store_true")
    args = ap.parse_args()

    tests = {r["code"]: r for r in load_json(TEST_RESULTS)}
    persisted = {r["code"]: r for r in load_json(PERSIST_RESULTS)}
    if not tests:
        print(f"no results at {TEST_RESULTS}")
        return 1
    audit = json.loads(AUDIT_RESULTS.read_text(encoding="utf-8")) if AUDIT_RESULTS.exists() else {}
    if not audit:
        print(
            f"no audit at {AUDIT_RESULTS}. Run scripts/prune_html_sweep_rows.py first: a "
            "source is only verified when a real posting survived the quality gate."
        )
        return 1

    verified_list = None
    if VERIFIED.exists():
        verified_list = set(json.loads(VERIFIED.read_text(encoding="utf-8")).get("sources", {}))

    data = json.loads(SOURCES.read_text(encoding="utf-8"))
    verified, disabled = apply_status(
        data, tests, persisted, audit, verified_list, date.today().isoformat()
    )

    if args.dry_run:
        for code, note in verified:
            print(f"ENABLE  {code}: {note}")
        for code in disabled:
            print(f"DISABLE {code}")
        return 0

    if args.commit_each:
        commit_each(verified, data)
    else:
        write_sources(data)

    print(
        f"updated {len(verified) + len(disabled)} entries: "
        f"{len(verified)} enabled, {len(disabled)} disabled"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Delete HTML-sweep rows that are not postings, and record what survived.

The 2026-10-21/22 sweep stored rows from ~70 auto-generated configs. Reading
them afterwards showed that most were the site's own navigation, news articles,
company profile pages, or bot-challenge screens. Counting them is not proof of
anything, so this script applies the pipeline's own gate
(``validation.html_scraper_quality.reject_reason``) to the stored rows and
removes the failures.

Two kinds of row go:

1. Any row from a source that is disabled in ``config/sources.json``. A
   disabled source is one the sweep proved cannot be scraped reliably, so its
   rows are a one-off artefact of the test run, not data.
2. Any row that fails the gate, even from an enabled source.

It writes ``reports/html_scraper_audit_results.json`` with per-source kept and
deleted counts; ``scripts/update_html_source_status.py`` reads that file so a
source only stays enabled if something survived here.

Run:
    uv run python scripts/prune_html_sweep_rows.py --dry-run
    uv run python scripts/prune_html_sweep_rows.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.validation.html_scraper_quality import reject_reason

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
SOURCES = ROOT / "config" / "sources.json"
VERIFIED = ROOT / "config" / "html_verified_sources.json"
OUT = ROOT / "reports" / "html_scraper_audit_results.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def config_info() -> dict[str, dict[str, str]]:
    info: dict[str, dict[str, str]] = {}
    for path in SITES.glob("*.json"):
        config = json.loads(path.read_text(encoding="utf-8"))
        info[path.stem] = {
            "host": urlparse(config.get("base_url") or "").netloc,
            "pattern": config.get("detail_url_pattern") or "",
        }
    return info


def disabled_codes() -> set[str]:
    data = json.loads(SOURCES.read_text(encoding="utf-8"))
    return {entry["code"] for entry in data["sources"] if not entry.get("enabled")}


def verified_codes() -> set[str]:
    """The sources a human checked page by page; everything else is a test run."""
    data = json.loads(VERIFIED.read_text(encoding="utf-8"))
    return set(data["sources"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-21T00:00:00+00:00")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", type=int, default=2, help="Reject examples per source")
    args = ap.parse_args()

    info = config_info()
    disabled = disabled_codes()
    verified = verified_codes()

    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT j.job_id, j.posting_date, s.source_code, j.job_title,
                       j.original_url, coalesce(d.description_clean, ''),
                       j.first_scraped_at, s.is_active
                FROM core.jobs j
                JOIN ref.sources s ON s.source_id = j.source_id
                LEFT JOIN core.job_descriptions d
                       ON d.job_id = j.job_id AND d.posting_date = j.posting_date
                WHERE j.first_scraped_at >= :since
                ORDER BY s.source_code, j.job_id
                """
            ),
            {"since": args.since},
        ).all()

    # Only touch sources that belong to this sweep: configs still on disk, or
    # codes the sweep disabled (their config is gone or they failed). A code
    # retired as a duplicate has no config and no sources.json entry any more,
    # so ref.sources.is_active is the only trace of it.
    in_scope = [row for row in rows if row[2] in info or row[2] in disabled or row[7] is False]

    keeps: dict[str, int] = defaultdict(int)
    deletes: list[tuple] = []
    deleted_per_source: dict[str, int] = defaultdict(int)
    examples: dict[str, list[str]] = defaultdict(list)
    reasons: dict[str, str] = {}

    for job_id, posting_date, code, title, url, desc, _, is_active in in_scope:
        if code not in verified or is_active is False:
            reason = "source not verified by the sweep audit"
        else:
            entry = info.get(code, {})
            reason = reject_reason(
                url,
                title,
                desc,
                site_host=entry.get("host", ""),
                detail_pattern=entry.get("pattern", ""),
            )
        if reason is None:
            keeps[code] += 1
            continue
        deletes.append((job_id, posting_date))
        deleted_per_source[code] += 1
        reasons.setdefault(code, reason)
        if len(examples[code]) < args.show:
            examples[code].append(f"{(title or '')[:48]!r} -> {reason}")

    print(f"{len(in_scope)} row(s) in scope since {args.since}")
    print(f"keep {len(in_scope) - len(deletes)}, delete {len(deletes)}\n")
    for code in sorted(set(keeps) | set(deleted_per_source)):
        print(f"{code:28} keep={keeps[code]:3} delete={deleted_per_source[code]:3}")
        for example in examples.get(code, []):
            print(f"     {example}")

    if args.dry_run:
        return 0

    if deletes:
        with get_session() as session:
            for job_id, posting_date in deletes:
                session.execute(
                    text(
                        "DELETE FROM core.job_descriptions "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {"job_id": job_id, "posting_date": posting_date},
                )
                session.execute(
                    text(
                        "DELETE FROM core.jobs "
                        "WHERE job_id = :job_id AND posting_date = :posting_date"
                    ),
                    {"job_id": job_id, "posting_date": posting_date},
                )
            session.commit()

    report = {
        code: {
            "kept": keeps.get(code, 0),
            "deleted": deleted_per_source.get(code, 0),
            "first_reason": reasons.get(code),
        }
        for code in sorted(set(keeps) | set(deleted_per_source))
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\ndeleted {len(deletes)} row(s); wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

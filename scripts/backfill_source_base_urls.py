"""Copy each site config's base_url into the registry row.

The generated configs were registered without a base_url, which made the
registry unable to answer "which codes point at the same board?" -- the exact
question that exposed hellojob/hellojob_az storing the same 14 postings twice.

Run:  uv run python scripts/backfill_source_base_urls.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction

SITES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "job_market_intel"
    / "scrapers"
    / "html_scraper"
    / "sites"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    updates: list[tuple[str, str]] = []
    for path in sorted(SITES.glob("*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if cfg.get("base_url"):
            updates.append((path.stem, cfg["base_url"].rstrip("/")))

    with get_session() as session:
        existing = dict(
            session.execute(text("SELECT source_code, base_url FROM ref.sources")).all()
        )
        todo = [
            (code, url)
            for code, url in updates
            if code in existing and not (existing.get(code) or "").strip()
        ]
        print(f"{len(updates)} configs, {len(todo)} registry rows need a base_url")
        for code, url in todo:
            print(f"  {code} -> {url}")
        if args.dry_run or not todo:
            return 0
        with transaction(session):
            for code, url in todo:
                session.execute(
                    text(
                        "UPDATE ref.sources SET base_url = :url, updated_at = now() "
                        "WHERE source_code = :code"
                    ),
                    {"url": url, "code": code},
                )
        print(f"updated {len(todo)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

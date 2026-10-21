"""Audit what the generic HTML scraper actually stored, per source.

The sweep only proved "at least one record parsed". It did not prove the record
was a job posting: the fallback builds a title from the URL slug, so a category
page such as /jobs/highest-paying parsed today would look like a posting.

Run:  uv run python scripts/audit_html_rows.py [--since 2026-10-21]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from sqlalchemy import text

from job_market_intel.db.session import get_session

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SUSPECT = (
    "saved",
    "highest-paying",
    "search",
    "login",
    "register",
    "sign-in",
    "signup",
    "all-jobs",
    "browse",
    "category",
    "categories",
    "career-advice",
    "companies",
    "employers",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-21")
    ap.add_argument("--show", type=int, default=3, help="Samples per source")
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT s.source_code, j.job_title, j.original_url,
                       coalesce(length(d.description_clean), 0) AS dlen,
                       j.is_duplicate_of
                FROM core.jobs j
                JOIN ref.sources s ON s.source_id = j.source_id
                LEFT JOIN core.job_descriptions d
                       ON d.job_id = j.job_id AND d.posting_date = j.posting_date
                WHERE j.posting_date >= :since
                ORDER BY s.source_code, j.job_id
                """
            ),
            {"since": args.since},
        ).all()

    per: dict[str, list[tuple]] = defaultdict(list)
    dup = 0
    for code, title, url, dlen, is_dup in rows:
        per[code].append((title or "", url or "", int(dlen)))
        if is_dup is not None:
            dup += 1

    print(f"{len(rows)} rows across {len(per)} sources since {args.since}")
    print(f"{dup} row(s) already flagged is_duplicate_of\n")
    suspects_total = 0
    for code in sorted(per):
        items = per[code]
        n = len(items)
        short = sum(1 for _, _, d in items if d < 200)
        suspect = sum(
            1
            for t, u, _ in items
            if any(k in (u or "").lower() for k in SUSPECT)
            or any(k in (t or "").lower() for k in ("saved jobs", "highest paying"))
        )
        suspects_total += suspect
        avg = sum(d for _, _, d in items) // max(1, len(items))
        flag = "  <-- SUSPECT" if suspect or short == n else ""
        print(
            f"{code:28} rows={n:3} no-desc={short:3} suspect-url={suspect:3} avg-desc={avg:5}{flag}"
        )
        for t, u, d in items[: args.show]:
            print(f"     {t[:60]!r} {u[:70]} desc={d}")

    print(f"\n{suspects_total} row(s) look like navigation/category links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Re-decode the JobMail rows written before the entity fix.

**The bug.** The board writes the employer's name and the ad title into the
JSON-LD with HTML entities still escaped -- ``O&#x27;Brien Recruitment``,
``Junior Estimator &amp; Administrator`` -- and BeautifulSoup does not touch
the JSON-LD block. The parser stored them verbatim, so the corpus held a
company called "O&#x27;Brien Recruitment" alongside the real one, and a
company called "O&#x27;Brien" is a different company from "O'Brien" as far as
the corpus's company de-duplication is concerned.

**Why this needs a repair.** The board's listing is sorted by date posted, so
the affected postings drift onto deeper pages as new ones arrive and a plain
re-scrape does not reliably reach them. The content hash covers the company
name, so re-saving an affected posting *does* correct it -- but only if the
scraper gets to that posting at all.

So this walks the rows that are still wrong, re-fetches each one's own stored
``original_url``, re-parses it, and re-saves it through the normal repository
path, which creates the decoded company row and re-points the job at it. The
company rows left with no jobs are then removed.

Run:  uv run python scripts/redecode_jobmail_entities.py --dry-run
      uv run python scripts/redecode_jobmail_entities.py --apply
"""

from __future__ import annotations

import argparse
import sys
import time

import requests
from loguru import logger
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction

UA = "job-market-intel-research (research@example.org)"


def affected_rows(session) -> list[dict]:
    return (
        session.execute(
            text("""
            SELECT j.job_id, j.source_job_id, j.original_url, j.job_title,
                   c.company_id, c.company_name
            FROM core.jobs j
            JOIN ref.sources src ON src.source_id = j.source_id
            JOIN core.companies c ON c.company_id = j.company_id
            WHERE src.source_code = 'jobmail'
              AND (j.job_title LIKE '%&#%' OR j.job_title LIKE '%&amp;%'
                   OR j.job_title LIKE '%&lt;%'
                   OR c.company_name LIKE '%&#%' OR c.company_name LIKE '%&amp;%')
            ORDER BY j.job_id
        """)
        )
        .mappings()
        .all()
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write the corrections.")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly do nothing. This is already the default; the flag is here so "
        "the command can be read as intent rather than as an omission.",
    )
    ap.add_argument("--delay", type=float, default=2.0, help="Seconds between fetches.")
    args = ap.parse_args(argv)

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-ZA,en;q=0.9"})

    with get_session() as db:
        rows = affected_rows(db)
        print(f"rows still holding HTML entities: {len(rows)}")
        if not rows:
            print("nothing to repair")
            return 0

        for row in rows:
            print(
                f"  {row['source_job_id']:<10} {row['job_title'][:44]!r} "
                f"@ {row['company_name'][:36]!r}"
            )

        if not args.apply:
            print("\n--dry-run: nothing written.")
            return 0

        from job_market_intel.cleaning.jobmail_cleaner import JobMailCleaner
        from job_market_intel.db.job_repository import JobRepository
        from job_market_intel.scrapers.jobmail.parser import parse_detail

        cleaner = JobMailCleaner()

        repo = JobRepository()
        source_id = db.execute(
            text("SELECT source_id FROM ref.sources WHERE source_code = 'jobmail'")
        ).scalar()
        fixed = 0
        for row in rows:
            url = row["original_url"]
            try:
                html = session.get(url, timeout=60).text
            except Exception as exc:  # noqa: BLE001
                logger.warning("{}: fetch failed: {}", url[:70], exc)
                time.sleep(args.delay)
                continue
            try:
                job = parse_detail(row["source_job_id"], html, url=url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("{}: parse failed: {}", url[:70], exc)
                time.sleep(args.delay)
                continue
            cleaned = cleaner.clean_job(job)
            with transaction(db):
                outcome = repo.save_cleaned_job(db, cleaned, source_id=int(source_id))
            fixed += 1
            logger.info("{}: {} -> {}", row["source_job_id"], outcome, cleaned.job_title)
            time.sleep(args.delay)

        # Company rows that ended up with no jobs at all.
        orphans = (
            db.execute(
                text("""
                SELECT c.company_id, c.company_name FROM core.companies c
                WHERE (c.company_name LIKE '%&#%' OR c.company_name LIKE '%&amp;%')
                  AND NOT EXISTS (SELECT 1 FROM core.jobs j WHERE j.company_id = c.company_id)
            """)
            )
            .mappings()
            .all()
        )
        for orphan in orphans:
            print(f"  removing orphan company {orphan['company_name']!r}")
        db.execute(
            text("""
                DELETE FROM core.companies c
                WHERE (c.company_name LIKE '%&#%' OR c.company_name LIKE '%&amp;%')
                  AND NOT EXISTS (SELECT 1 FROM core.jobs j WHERE j.company_id = c.company_id)
            """)
        )
        db.commit()
        print(f"\nrepaired {fixed} row(s); removed {len(orphans)} orphan company row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

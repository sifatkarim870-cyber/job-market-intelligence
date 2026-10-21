"""Delete HTML-scraper rows that the quality gate says are not job postings.

The 2026-10-21 sweep stored 578 rows from auto-generated configs. An audit found
that most were the site's own navigation (``/job-search/operations-jobs``,
``/jobs/today/``), news articles, or bot-challenge pages. They are not postings
and they must not reach HuggingFace, Kaggle, or any published count.

This applies exactly the same gate the pipeline now applies before persisting
(``validation.html_scraper_quality.reject_reason``), so what is deleted here is
what would never have been stored after the fix.

Scope is narrow on purpose: only rows whose ``first_scraped_at`` falls on or
after --since, and only sources that have a site config. A hand-tuned scraper's
history is not touched.

Run:  uv run python scripts/purge_non_job_rows.py --dry-run
      uv run python scripts/purge_non_job_rows.py
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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def config_hosts() -> dict[str, str]:
    hosts: dict[str, str] = {}
    for path in SITES.glob("*.json"):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        base = cfg.get("base_url") or ""
        hosts[path.stem] = urlparse(base).netloc if base else ""
    return hosts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-21")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", type=int, default=2, help="Example rejects per source")
    args = ap.parse_args()

    hosts = config_hosts()

    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT j.job_id, j.posting_date, s.source_code, j.job_title,
                       j.original_url, coalesce(d.description_clean, '')
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

    config_rows = [r for r in rows if r[2] in hosts]
    rejects: list[tuple] = []
    kept_per_source: dict[str, int] = defaultdict(int)
    reject_per_source: dict[str, int] = defaultdict(int)
    examples: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for job_id, posting_date, code, title, url, desc in config_rows:
        reason = reject_reason(url, title, desc, site_host=hosts.get(code, ""))
        if reason is None:
            kept_per_source[code] += 1
        else:
            rejects.append((job_id, posting_date))
            reject_per_source[code] += 1
            if len(examples[code]) < args.show:
                examples[code].append(((title or "")[:50], reason))

    print(f"{len(config_rows)} config-driven row(s) since {args.since}")
    print(f"{len(rejects)} reject(s), {len(config_rows) - len(rejects)} kept\n")
    for code in sorted(set(kept_per_source) | set(reject_per_source)):
        print(f"{code:28} kept={kept_per_source[code]:3} rejected={reject_per_source[code]:3}")
        for title, reason in examples.get(code, []):
            print(f"     {title!r} -> {reason}")

    if args.dry_run or not rejects:
        return 0

    with get_session() as session:
        deleted_desc = 0
        for job_id, posting_date in rejects:
            deleted_desc += session.execute(
                text(
                    "DELETE FROM core.job_descriptions "
                    "WHERE job_id = :job_id AND posting_date = :posting_date"
                ),
                {"job_id": job_id, "posting_date": posting_date},
            ).rowcount
            session.execute(
                text(
                    "DELETE FROM core.jobs WHERE job_id = :job_id AND posting_date = :posting_date"
                ),
                {"job_id": job_id, "posting_date": posting_date},
            )
        session.commit()
    print(f"\ndeleted {len(rejects)} job row(s) and {deleted_desc} description row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

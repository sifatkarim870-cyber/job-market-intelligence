"""Per-source data check: how many jobs each source has in the target
database, and when it last ran.

This is the one-command answer to "is scraper X landing data in Neon?"
(default: whatever DATABASE_URL points at -- Neon for this repo; export
DATABASE_URL=LOCAL_DATABASE_URL's value first if you want the local side).

Usage:
    uv run python scripts/check_sources.py
"""

from __future__ import annotations

from sqlalchemy import text

from job_market_intel.db.session import get_session


def main() -> int:
    with get_session() as session:
        # Scalar subqueries instead of joins: joining jobs to sessions
        # multiplies rows (every job x every session of that source) and
        # silently inflates the counts.
        rows = session.execute(text(
            """
            SELECT s.source_code,
                   s.source_name,
                   s.is_active,
                   (SELECT count(*) FROM core.jobs j
                     WHERE j.source_id = s.source_id) AS jobs,
                   (SELECT min(posting_date) FROM core.jobs j
                     WHERE j.source_id = s.source_id) AS oldest_posting,
                   (SELECT max(posting_date) FROM core.jobs j
                     WHERE j.source_id = s.source_id) AS newest_posting,
                   (SELECT max(ss.started_at) FROM ops.scraping_sessions ss
                     WHERE ss.source_id = s.source_id) AS last_run,
                   (SELECT ss2.status FROM ops.scraping_sessions ss2
                     WHERE ss2.source_id = s.source_id
                     ORDER BY ss2.session_id DESC LIMIT 1) AS last_status
            FROM ref.sources s
            ORDER BY jobs DESC, s.source_code
            """
        )).all()
        target = session.get_bind().url.render_as_string(hide_password=True)

    print(f"Target database: {target}")
    print()
    header = f"{'source_code':<20} {'jobs':>7} {'active':>7}  {'last run (UTC)':<22} {'status':<10} posting dates"
    print(header)
    print("-" * len(header))
    for r in rows:
        jobs = r.jobs
        last_run = r.last_run.strftime("%Y-%m-%d %H:%M") if r.last_run else "-"
        status = r.last_status or "-"
        dates = (
            f"{r.oldest_posting} .. {r.newest_posting}" if jobs else ""
        )
        active = "yes" if r.is_active else "no"
        print(f"{r.source_code:<20} {jobs:>7} {active:>7}  {last_run:<22} {status:<10} {dates}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

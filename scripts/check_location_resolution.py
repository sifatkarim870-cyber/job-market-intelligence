"""Ad-hoc check: summarize Step 28 geographic resolution results.

Not a batch job -- geographic resolution runs inline from
db.job_repository.save_cleaned_job (see
normalization/geographic_resolution.py's module docstring for why a
deferred batch job isn't possible here). This script just reports on
what inline resolution has produced so far: breakdown by match_method
(how many raw strings resolved to a real city/region/country vs. fell
back to remote_global unresolved), plus a sample of unmatched raw
strings worth reviewing for possible ref.cities/ref.countries seed
coverage gaps.

Usage:
    uv run python scripts/check_location_resolution.py
"""

from __future__ import annotations

from sqlalchemy import text

from job_market_intel.db.session import get_session


def main() -> int:
    with get_session() as session:
        totals = session.execute(
            text(
                "SELECT match_method, count(*) AS n FROM core.location_aliases "
                "GROUP BY match_method ORDER BY n DESC"
            )
        ).all()

        unresolved_jobs = session.execute(
            text("SELECT count(*) FROM core.jobs WHERE location_id IS NULL")
        ).scalar()

        sample_unmatched = session.execute(
            text(
                "SELECT raw_location_text, source_id, created_at FROM core.location_aliases "
                "WHERE match_method = 'fallback_unmatched' "
                "ORDER BY created_at DESC LIMIT 20"
            )
        ).all()

    print()
    print("=" * 70)
    print("STEP 28 — GEOGRAPHIC RESOLUTION SUMMARY")
    print("=" * 70)
    print(f"{'match_method':<20} count")
    print("-" * 30)
    total = 0
    for row in totals:
        print(f"{row.match_method:<20} {row.n}")
        total += row.n
    print("-" * 30)
    print(f"{'total resolved strings':<20} {total}")
    print()
    print(
        f"core.jobs rows with location_id still NULL: {unresolved_jobs} "
        "(includes every job ingested before Step 28 deployed -- see "
        "migrations/add_location_aliases_table.sql's FOLLOW-UP note; these "
        "cannot be backfilled)."
    )

    if sample_unmatched:
        print()
        print("Most recent unmatched raw strings (candidates for widening")
        print("ref.cities/ref.countries seed coverage, per source_id):")
        for row in sample_unmatched:
            print(f"  '{row.raw_location_text}' (source_id={row.source_id})")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

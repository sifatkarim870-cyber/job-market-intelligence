"""One-off maintenance: activate specific sources in ref.sources.

This exists because seed_sources() deliberately excludes is_active from
its update_cols (see the comment in seed/sources.py) — once a source is
live, re-running the seed script must never silently deactivate it. That
same protection means editing the True/False literal in seed/sources.py
and re-running the seed has NO effect on a source that's already been
inserted; only a direct UPDATE (this script) actually flips it.

Usage:
    uv run python scripts/activate_sources.py weworkremotely remotive
    uv run python scripts/activate_sources.py --deactivate some_source
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from job_market_intel.db.session import get_session


def main() -> int:
    parser = argparse.ArgumentParser(description="Activate or deactivate ref.sources rows.")
    parser.add_argument("source_codes", nargs="+", help="One or more source_code values.")
    parser.add_argument(
        "--deactivate",
        action="store_true",
        help="Set is_active=False instead of True.",
    )
    args = parser.parse_args()

    target_value = not args.deactivate

    with get_session() as session:
        result = session.execute(
            text(
                "UPDATE ref.sources SET is_active = :active, updated_at = now() "
                "WHERE source_code = ANY(:codes) "
                "RETURNING source_code, is_active"
            ),
            {"active": target_value, "codes": args.source_codes},
        )
        updated_rows = result.all()

    found_codes = {row.source_code for row in updated_rows}
    missing_codes = set(args.source_codes) - found_codes

    print(f"Updated {len(updated_rows)} row(s):")
    for row in updated_rows:
        print(f"  {row.source_code}: is_active = {row.is_active}")

    if missing_codes:
        print(f"WARNING: no matching row found for: {', '.join(sorted(missing_codes))}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

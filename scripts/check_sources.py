"""Ad-hoc check: print every row in ref.sources.

Usage:
    uv run python scripts/check_sources.py
"""

from __future__ import annotations

from sqlalchemy import text

from job_market_intel.db.session import get_session


def main() -> int:
    with get_session() as session:
        rows = session.execute(
            text("SELECT source_code, source_name, is_active FROM ref.sources ORDER BY source_code")
        ).all()

    print(f"{'source_code':<20} {'source_name':<25} is_active")
    print("-" * 55)
    for row in rows:
        print(f"{row.source_code:<20} {row.source_name:<25} {row.is_active}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

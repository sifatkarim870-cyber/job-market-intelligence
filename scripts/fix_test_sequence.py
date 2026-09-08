"""One-off fix: reset the exhausted ref.countries_country_id_seq in the TEST database.

Repeated integration-test runs (each ``pytest`` invocation calls
``_run_all_steps`` once per parametrized case in ``TestFullPopulation``,
re-running every seed function including ``seed_countries``) advance
PostgreSQL's identity sequence on every attempted upsert row, even ones
that resolve as no-op ``ON CONFLICT`` updates. Sequences never roll back.
Over many test runs across this project's history, the sequence finally
exceeded ``ref.countries.country_id``'s SMALLINT ceiling (32,767).

This targets TEST_DATABASE_URL specifically (not your regular dev
DATABASE_URL) using the same "temporarily point DATABASE_URL at
TEST_DATABASE_URL" pattern tests/integration/conftest.py already uses,
rather than hand-rolling a second engine-creation path.

Usage:
    uv run python scripts/fix_test_sequence.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text


def main() -> int:
    test_db_url = os.environ.get("TEST_DATABASE_URL")
    if not test_db_url:
        print("TEST_DATABASE_URL is not set — nothing to do.", file=sys.stderr)
        return 1

    # Must happen before importing job_market_intel.db.session, since that
    # module's engine is created lazily but bound to whatever DATABASE_URL
    # is set at first use.
    os.environ["DATABASE_URL"] = test_db_url

    from job_market_intel.db.session import get_session

    with get_session() as session:
        before = session.execute(
            text("SELECT last_value FROM ref.countries_country_id_seq")
        ).scalar_one()
        print(f"Sequence value before reset: {before}")

        new_value = session.execute(
            text(
                "SELECT setval("
                "  'ref.countries_country_id_seq',"
                "  COALESCE((SELECT MAX(country_id) FROM ref.countries), 0) + 1,"
                "  false"
                ")"
            )
        ).scalar_one()
        print(f"Sequence value after reset:  {new_value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

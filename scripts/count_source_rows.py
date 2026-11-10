"""Print how many core.jobs rows a source has in the target database.

Used by the scrape workflows to decide whether an export is worth running after
a failed or partially failed scraper. The CI database starts with reference data
only (``core.jobs`` is deliberately not seeded), so a non-zero count means this
run persisted something.

Usage:
    python scripts/count_source_rows.py --source remoteok
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from job_market_intel.db import get_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    args = parser.parse_args(argv)

    with get_engine().connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM core.jobs j "
                "JOIN ref.sources s ON s.source_id = j.source_id "
                "WHERE s.source_code = :code"
            ),
            {"code": args.source},
        ).scalar_one()
    print(int(count))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Give every job a salary record, using its own source's declared constants.

The problem
-----------
``salary.job_salaries`` had a row for 105,544 of 132,808 jobs (2026-10-19).
The 27,679 without one were all CI-merged jobs whose posting carries **no
amount** -- the merge wrote a salary row only when the shard had a figure
(``merge_incoming_shards.py``), and it skipped the salary insert entirely for
a job that already existed. So the same source's rows were stored differently
depending on whether CI or the local run created them: a locally-created job
always got a placeholder row (``job_repository`` writes one for every job),
and a merged one did not.

The repair
----------
For a source whose rows all share ONE ``(pay_period, currency)`` combination,
that combination is the source's declared constant -- the same value its
cleaner writes on every job -- so the missing rows can be reconstructed
exactly. Measured over the corpus, **26 of 43 sources are constant**, covering
22,755 of the missing rows.

The remaining rows belong to sources that publish a per-record currency or
pay period (glints, reed, himalayas and so on) or to a source with no salary
record at all (``emploitic``). Those are **not** reconstructed: the value
cannot be derived without the original shard. They are filled by the next CI
run of those sources, now that the merge keeps a salary row whenever the
shard says anything about pay.

Nothing here guesses a figure. Every row written has ``salary_min`` and
``salary_max`` NULL and ``salary_disclosed`` False -- it says "this source
declares this currency and pay period, and publishes no amount", which is
exactly what the local path already stores for the same postings.

Run:  uv run python scripts/backfill_missing_salary_rows.py --dry-run
      uv run python scripts/backfill_missing_salary_rows.py --apply
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger
from sqlalchemy import text

from job_market_intel.db.session import get_session


def survey(session) -> tuple[dict, dict]:
    """(constant sources, everything else).

    ``constant[source_code] = (pay_period, currency_iso, missing_count)`` for a
    source whose existing salary rows all share one combination.
    """
    combos = (
        session.execute(
            text("""
        SELECT src.source_code, sal.pay_period, cur.iso_code AS currency,
               count(*) AS n
        FROM core.jobs j
        JOIN ref.sources src ON src.source_id = j.source_id
        JOIN salary.job_salaries sal
             ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
        JOIN ref.currencies cur ON cur.currency_id = sal.currency_id
        GROUP BY 1, 2, 3
    """)
        )
        .mappings()
        .all()
    )

    by_source: dict[str, list] = {}
    for row in combos:
        by_source.setdefault(row["source_code"], []).append(row)

    missing = dict(
        session.execute(
            text("""
        SELECT src.source_code, count(*) AS n
        FROM core.jobs j
        JOIN ref.sources src ON src.source_id = j.source_id
        LEFT JOIN salary.job_salaries sal
               ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
        WHERE sal.job_salary_id IS NULL
        GROUP BY 1
    """)
        ).all()
    )

    constant: dict[str, tuple] = {}
    for code, rows in by_source.items():
        if code not in missing:
            continue
        if len(rows) == 1:
            constant[code] = (rows[0]["pay_period"], rows[0]["currency"], missing[code])
    return constant, missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write the rows (default is a dry run).")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly do nothing. This is already the default; the flag is here so "
        "the command can be read as intent rather than as an omission.",
    )
    args = ap.parse_args(argv)

    with get_session() as session:
        constant, missing = survey(session)
        total_missing = sum(missing.values())
        total_constant = sum(n for (_p, _c, n) in constant.values())

        print("=" * 78)
        print("BACKFILLING MISSING salary.job_salaries ROWS")
        print("=" * 78)
        print(f"jobs with no salary row      : {total_missing:,}")
        print(f"reconstructable (constant src): {total_constant:,}")
        print(f"not reconstructable           : {total_missing - total_constant:,}")
        print(f"mode                         : {'APPLY' if args.apply else 'DRY RUN'}")

        print("\n--- reconstructable sources ---")
        for code, (period, currency, n) in sorted(constant.items(), key=lambda kv: -kv[1][2]):
            print(f"   {code:<20} {n:>6} rows  pay_period={period!r} currency={currency!r}")

        skipped = {c: n for c, n in missing.items() if c not in constant}
        print(f"\n--- NOT reconstructable ({len(skipped)} source(s)) ---")
        for code, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"   {code:<20} {n:>6} rows")
        print("   These publish a per-record currency or pay period, so the value")
        print("   cannot be derived; the next CI run of each fills them now that")
        print("   the merge keeps a salary row whenever the shard says anything.")

        if not args.apply:
            print("\n--dry-run: nothing written.")
            return 0

        written = 0
        for code, (period, currency, _n) in constant.items():
            result = session.execute(
                text("""
                INSERT INTO salary.job_salaries (
                    job_id, posting_date, salary_min, salary_max, currency_id,
                    pay_period, salary_disclosed, is_negotiable,
                    normalized_annual_min_usd, normalized_annual_max_usd
                )
                SELECT j.job_id, j.posting_date, NULL, NULL, cur.currency_id,
                       :period, FALSE, NULL, NULL, NULL
                FROM core.jobs j
                JOIN ref.sources src ON src.source_id = j.source_id
                JOIN ref.currencies cur ON cur.iso_code = :currency
                LEFT JOIN salary.job_salaries sal
                       ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
                WHERE src.source_code = :code AND sal.job_salary_id IS NULL
                ON CONFLICT (job_id) DO NOTHING
                """),
                {"code": code, "period": period, "currency": currency},
            )
            written += result.rowcount or 0
            logger.info("{}: {} row(s) written", code, result.rowcount or 0)
        session.commit()
        print(f"\nwritten: {written:,} row(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

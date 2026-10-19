"""The backfill script's source survey.

``scripts/backfill_missing_salary_rows.py`` reconstructs a missing
``salary.job_salaries`` row from its source's OWN declared constants -- but
only for a source whose existing salary rows all share one
``(pay_period, currency)`` combination. A source that publishes a per-record
currency or pay period cannot be reconstructed and must not be guessed at.

These tests use the real local database, the same idiom as
``tests/unit/corpus/test_merge_incoming_shards.py``.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from sqlalchemy import create_engine, text

DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

BACKFILL = (
    pathlib.Path(__file__).resolve().parents[3] / "scripts" / "backfill_missing_salary_rows.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("backfill_salary_mod", BACKFILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _module()


@pytest.fixture(scope="module")
def engine():
    try:
        eng = create_engine(DSN, connect_args={"connect_timeout": 5})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        yield eng
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local Postgres unavailable: {str(exc)[:80]}")


class TestSurvey:
    def test_it_returns_two_buckets(self, mod, engine):
        with engine.connect() as conn:
            constant, missing = mod.survey(conn)
        assert isinstance(constant, dict)
        assert isinstance(missing, dict)

    def test_every_constant_source_has_exactly_one_combination(self, mod, engine):
        """The whole point: a constant source is one that varies never.

        If a source appears in the constant bucket, every salary row it has
        must share the same pay_period and currency -- otherwise the
        reconstruction would be inventing a value for some of its jobs.
        """
        with engine.connect() as conn:
            constant, _missing = mod.survey(conn)
            for code, (period, currency, _n) in constant.items():
                rows = conn.execute(
                    text("""
                        SELECT DISTINCT sal.pay_period, cur.iso_code
                        FROM core.jobs j
                        JOIN ref.sources src ON src.source_id = j.source_id
                        JOIN salary.job_salaries sal
                             ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
                        JOIN ref.currencies cur ON cur.currency_id = sal.currency_id
                        WHERE src.source_code = :code
                    """),
                    {"code": code},
                ).all()
                assert len(rows) == 1, f"{code} has {len(rows)} combinations: {rows}"
                assert rows[0][0] == period and rows[0][1] == currency

    def test_a_source_that_varies_is_not_in_the_constant_bucket(self, mod, engine):
        """glints publishes a per-record currency, so it must be excluded."""
        with engine.connect() as conn:
            constant, _missing = mod.survey(conn)
            combos = conn.execute(
                text("""
                    SELECT DISTINCT sal.pay_period, cur.iso_code
                    FROM core.jobs j
                    JOIN ref.sources src ON src.source_id = j.source_id
                    JOIN salary.job_salaries sal
                         ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
                    JOIN ref.currencies cur ON cur.currency_id = sal.currency_id
                    WHERE src.source_code = 'glints'
                """)
            ).all()
        if len(combos) > 1:
            assert "glints" not in constant, (
                "glints varies its currency per record; reconstructing a single "
                "combination for it would be inventing a value"
            )

    def test_a_source_with_no_salary_row_is_not_reconstructable(self, mod, engine):
        with engine.connect() as conn:
            constant, missing = mod.survey(conn)
            no_salary = conn.execute(
                text("""
                    SELECT src.source_code
                    FROM core.jobs j
                    JOIN ref.sources src ON src.source_id = j.source_id
                    LEFT JOIN salary.job_salaries sal
                           ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
                    GROUP BY 1
                    HAVING count(sal.job_salary_id) = 0
                """)
            ).all()
        for (code,) in no_salary:
            # Every job of such a source lacks a row, so there is nothing to
            # copy a combination from.
            assert code not in constant, f"{code} has no salary row to copy from"

    def test_the_counts_add_up(self, mod, engine):
        with engine.connect() as conn:
            constant, missing = mod.survey(conn)
        total = conn_total = None
        with engine.connect() as conn:
            conn_total = conn.execute(
                text("""
                SELECT count(*) FROM core.jobs j
                LEFT JOIN salary.job_salaries sal
                       ON sal.job_id = j.job_id AND sal.posting_date = j.posting_date
                WHERE sal.job_salary_id IS NULL
            """)
            ).scalar_one()
        total = sum(missing.values())
        assert total == conn_total, (total, conn_total)
        assert total == sum(n for (_p, _c, n) in constant.values()) + sum(
            n for c, n in missing.items() if c not in constant
        )


class TestItDoesNotInventFigures:
    def test_every_backfilled_row_would_carry_no_amount(self):
        """The script's own INSERT: salary_min and salary_max are NULL."""
        source = BACKFILL.read_text(encoding="utf-8")
        assert "SELECT j.job_id, j.posting_date, NULL, NULL, cur.currency_id" in source
        assert "FALSE, NULL, NULL, NULL" in source

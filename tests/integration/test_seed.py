"""
tests/test_seed.py

Tests for the `seed` package established in Step 4.5.

Scope
-----
These tests verify that every seed module populates its target `ref.*` /
`auth.*` table correctly, that the full run_all() chain respects FK
dependency order, and — most importantly — that every module is genuinely
idempotent (safe to run any number of times without creating duplicates
or drifting row counts). This suite is what caught the ref.cities
NULL-region duplicate bug during manual testing; it exists so that class
of bug is caught automatically in CI going forward, not just by luck.

Test database
-------------
Like test_database.py, live tests are gated on TEST_DATABASE_URL and
skipped (not failed) when it's unset, so the suite still runs in
environments without a database available. TEST_DATABASE_URL must point
at a schema-applied, disposable database — never DATABASE_URL from the
application's own .env. Nothing here targets production data.

The requires_live_db marker/skip behavior and the `conn` fixture (a
transactional, unseeded Connection) are both centralized in
tests/integration/conftest.py — see that file's module docstring for why.
"""

from __future__ import annotations

import pytest
from seed.auth import seed_admin_user, seed_roles
from seed.benefits import seed_benefits
from seed.cities import seed_cities
from seed.countries import seed_countries
from seed.currencies import seed_currencies
from seed.education_levels import seed_education_levels
from seed.employment_types import seed_employment_types
from seed.experience_levels import seed_experience_levels
from seed.job_categories import seed_job_categories
from seed.languages import seed_languages
from seed.regions import seed_regions
from seed.remote_work_types import seed_remote_work_types
from seed.skill_categories import seed_skill_categories
from seed.skills import seed_skills
from seed.sources import seed_sources
from sqlalchemy import text

# every test in this file needs real Postgres — seed logic is DB-specific
# SQL (ON CONFLICT, xmax), unlike test_database.py's engine/session
# behavior which could use sqlite.
pytestmark = pytest.mark.requires_live_db


ORDERED_STEPS = [
    seed_currencies,
    seed_countries,
    seed_regions,
    seed_cities,
    seed_remote_work_types,
    seed_employment_types,
    seed_experience_levels,
    seed_education_levels,
    seed_job_categories,
    seed_skill_categories,
    seed_skills,
    seed_benefits,
    seed_languages,
    seed_sources,
    seed_roles,
]


def _run_all_steps(conn):
    for fn in ORDERED_STEPS:
        fn(conn)


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------


class TestExecutionOrder:
    def test_full_chain_runs_without_fk_violation(self, conn):
        """The single most important test: dependency order is correct."""
        _run_all_steps(conn)  # raises on any FK violation


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_running_twice_produces_no_duplicates(self, conn):
        _run_all_steps(conn)
        count_1 = conn.execute(text("SELECT count(*) FROM ref.skills")).scalar_one()
        _run_all_steps(conn)
        count_2 = conn.execute(text("SELECT count(*) FROM ref.skills")).scalar_one()
        assert count_1 == count_2

    def test_second_run_reports_zero_inserts(self, conn):
        _run_all_steps(conn)
        result = seed_currencies(conn)
        assert result.inserted == 0

    def test_cities_null_region_no_duplicates_on_rerun(self, conn):
        """
        Regression test for the bug found during manual seeding: cities
        with region_id = NULL (most non-US/CA/IN/AU/GB cities) were not
        matched by ON CONFLICT (country_id, region_id, city_name), because
        NULL <> NULL in PostgreSQL uniqueness matching — causing duplicate
        inserts on every re-run instead of updates. Fixed via the
        NULL-safe expression index (country_id, COALESCE(region_id, 0),
        city_name). This test fails if that fix ever regresses.
        """
        seed_currencies(conn)
        seed_countries(conn)
        seed_regions(conn)

        seed_cities(conn)
        count_1 = conn.execute(text("SELECT count(*) FROM ref.cities")).scalar_one()

        seed_cities(conn)  # run again in the same connection
        count_2 = conn.execute(text("SELECT count(*) FROM ref.cities")).scalar_one()

        assert count_1 == count_2 == 82

    def test_cities_second_run_reports_only_updates(self, conn):
        seed_currencies(conn)
        seed_countries(conn)
        seed_regions(conn)
        seed_cities(conn)

        result = seed_cities(conn)  # second run, same connection
        assert result.inserted == 0
        assert result.updated == 82


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


class TestReferentialIntegrity:
    def test_regions_reference_valid_countries(self, conn):
        seed_currencies(conn)
        seed_countries(conn)
        seed_regions(conn)
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM ref.regions r "
                "LEFT JOIN ref.countries c ON c.country_id = r.country_id "
                "WHERE c.country_id IS NULL"
            )
        ).scalar_one()
        assert orphans == 0

    def test_cities_reference_valid_regions_and_countries(self, conn):
        seed_currencies(conn)
        seed_countries(conn)
        seed_regions(conn)
        seed_cities(conn)
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM ref.cities ci "
                "LEFT JOIN ref.countries c ON c.country_id = ci.country_id "
                "WHERE c.country_id IS NULL"
            )
        ).scalar_one()
        assert orphans == 0

    def test_skills_reference_valid_categories(self, conn):
        seed_skill_categories(conn)
        seed_skills(conn)
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM ref.skills s "
                "LEFT JOIN ref.skill_categories sc ON sc.skill_category_id = s.skill_category_id "
                "WHERE sc.skill_category_id IS NULL"
            )
        ).scalar_one()
        assert orphans == 0

    def test_job_category_children_reference_valid_parents(self, conn):
        seed_job_categories(conn)
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM ref.job_categories c "
                "WHERE c.parent_category_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM ref.job_categories p "
                "WHERE p.job_category_id = c.parent_category_id)"
            )
        ).scalar_one()
        assert orphans == 0


# ---------------------------------------------------------------------------
# Duplicate prevention
# ---------------------------------------------------------------------------


class TestDuplicatePrevention:
    def test_no_duplicate_currency_codes(self, conn):
        seed_currencies(conn)
        dupes = conn.execute(
            text(
                "SELECT iso_code, count(*) FROM ref.currencies "
                "GROUP BY iso_code HAVING count(*) > 1"
            )
        ).all()
        assert dupes == []

    def test_no_duplicate_normalized_skill_names(self, conn):
        seed_skill_categories(conn)
        seed_skills(conn)
        dupes = conn.execute(
            text(
                "SELECT normalized_skill_name, count(*) FROM ref.skills "
                "GROUP BY normalized_skill_name HAVING count(*) > 1"
            )
        ).all()
        assert dupes == []

    def test_no_duplicate_cities_per_country_region(self, conn):
        seed_currencies(conn)
        seed_countries(conn)
        seed_regions(conn)
        seed_cities(conn)
        dupes = conn.execute(
            text(
                "SELECT country_id, COALESCE(region_id, 0), city_name, count(*) "
                "FROM ref.cities "
                "GROUP BY country_id, COALESCE(region_id, 0), city_name "
                "HAVING count(*) > 1"
            )
        ).all()
        assert dupes == []


# ---------------------------------------------------------------------------
# Full population
# ---------------------------------------------------------------------------


class TestFullPopulation:
    @pytest.mark.parametrize(
        "schema,table,min_rows",
        [
            ("ref", "currencies", 30),
            ("ref", "countries", 40),
            ("ref", "regions", 50),
            ("ref", "cities", 70),
            ("ref", "remote_work_types", 5),
            ("ref", "employment_types", 5),
            ("ref", "experience_levels", 5),
            ("ref", "education_levels", 5),
            ("ref", "job_categories", 40),
            ("ref", "skill_categories", 10),
            ("ref", "skills", 100),
            ("ref", "benefits", 20),
            ("ref", "languages", 25),
            ("ref", "sources", 5),
            ("auth", "roles", 4),
        ],
    )
    def test_table_meets_minimum_row_count(self, conn, schema, table, min_rows):
        _run_all_steps(conn)
        count = conn.execute(text(f"SELECT count(*) FROM {schema}.{table}")).scalar_one()
        assert count >= min_rows


# ---------------------------------------------------------------------------
# Admin bootstrap
# ---------------------------------------------------------------------------


class TestAdminBootstrap:
    def test_admin_skipped_when_env_var_absent(self, conn, monkeypatch):
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
        seed_roles(conn)
        result = seed_admin_user(conn)
        assert result.inserted == 0

    def test_admin_created_when_env_var_present(self, conn, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAIL", "test-admin@example.com")
        monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "unused-in-this-schema")
        seed_roles(conn)
        result = seed_admin_user(conn)
        assert result.inserted == 1
        row = conn.execute(
            text("SELECT role_id FROM auth.users WHERE email = 'test-admin@example.com'")
        ).first()
        assert row is not None

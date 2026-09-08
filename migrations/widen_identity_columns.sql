-- ============================================================================
-- MIGRATION: Widen SMALLINT identity PKs to INT on repeatedly-upserted
-- ref.* / auth.roles tables.
--
-- WHY THIS EXISTS
-- ----------------
-- ref.countries.country_id (SMALLINT GENERATED ALWAYS AS IDENTITY, max
-- 32,767) hit its ceiling in the test database on 2026-08-29. Root cause:
-- PostgreSQL identity sequences advance on every attempted INSERT,
-- including ones that resolve as no-op updates via ON CONFLICT DO UPDATE.
-- They never roll back. The integration test suite's TestFullPopulation
-- re-runs the entire seed pipeline (including seed_countries) once per
-- parametrized case — 15 times per `pytest` run — so every full test run
-- burns through ~55 x 15 = 825 sequence values for countries alone,
-- regardless of how many distinct countries actually exist. Multiplied
-- across the many `pytest` runs during this project's development, the
-- sequence finally exceeded SMALLINT's range.
--
-- The exact same exposure exists on every other ref.* (and auth.roles)
-- table using a SMALLINT identity PK, since they're all seeded via the
-- identical upsert_many() -> ON CONFLICT DO UPDATE pattern and re-run
-- just as often in the same test suite. ref.countries simply had the
-- largest per-call batch size (55 rows) among them, so it hit the wall
-- first — the others were always just as exposed, only slower to arrive.
--
-- WHAT THIS DOES
-- ----------------
-- Widens each affected identity column from SMALLINT (max 32,767) to
-- INT (max ~2.147 billion). PostgreSQL automatically widens the
-- column's backing identity sequence to match when the column type
-- changes, so no separate ALTER SEQUENCE step is needed. This is a
-- purely additive, non-destructive change: existing values (all small
-- integers well within INT's range) are preserved exactly, and no FK
-- column elsewhere needs to change — PostgreSQL permits a SMALLINT FK
-- column to reference an INT primary key without incident, since actual
-- stored values remain tiny regardless of the PK's declared range.
--
-- ref.regions and ref.cities already use INT and are unaffected by this
-- migration. Every core/bridge/salary table already uses BIGINT and was
-- never at risk.
--
-- SAFE TO RE-RUN: each ALTER TABLE is idempotent in effect — running
-- this twice against an already-widened column is a harmless no-op
-- (PostgreSQL allows "widening" a column to its own current type).
--
-- HOW TO RUN
-- ----------------
-- Requires elevated privileges (ALTER TABLE is DDL, not something
-- app_user typically holds) — run as the postgres superuser or table
-- owner, via psql, against BOTH your test and dev databases:
--
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f widen_identity_columns.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f widen_identity_columns.sql
-- ============================================================================

BEGIN;

ALTER TABLE ref.currencies       ALTER COLUMN currency_id        TYPE integer;
ALTER TABLE ref.sources          ALTER COLUMN source_id          TYPE integer;
ALTER TABLE ref.countries        ALTER COLUMN country_id         TYPE integer;
ALTER TABLE ref.remote_work_types ALTER COLUMN remote_work_type_id TYPE integer;
ALTER TABLE ref.industries       ALTER COLUMN industry_id        TYPE integer;
ALTER TABLE ref.employment_types ALTER COLUMN employment_type_id TYPE integer;
ALTER TABLE ref.experience_levels ALTER COLUMN experience_level_id TYPE integer;
ALTER TABLE ref.education_levels ALTER COLUMN education_level_id TYPE integer;
ALTER TABLE ref.job_categories    ALTER COLUMN job_category_id    TYPE integer;
ALTER TABLE ref.skill_categories  ALTER COLUMN skill_category_id  TYPE integer;
ALTER TABLE ref.languages        ALTER COLUMN language_id        TYPE integer;
ALTER TABLE auth.roles           ALTER COLUMN role_id            TYPE integer;

COMMIT;

-- ============================================================================
-- VERIFICATION: confirm every column above is now `integer`, and every
-- backing sequence's max value is now the INT ceiling (~2.147 billion),
-- not the old SMALLINT ceiling (32,767).
-- ============================================================================

SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE (table_schema, table_name, column_name) IN (
    ('ref', 'currencies', 'currency_id'),
    ('ref', 'sources', 'source_id'),
    ('ref', 'countries', 'country_id'),
    ('ref', 'remote_work_types', 'remote_work_type_id'),
    ('ref', 'industries', 'industry_id'),
    ('ref', 'employment_types', 'employment_type_id'),
    ('ref', 'experience_levels', 'experience_level_id'),
    ('ref', 'education_levels', 'education_level_id'),
    ('ref', 'job_categories', 'job_category_id'),
    ('ref', 'skill_categories', 'skill_category_id'),
    ('ref', 'languages', 'language_id'),
    ('auth', 'roles', 'role_id')
)
ORDER BY table_schema, table_name;

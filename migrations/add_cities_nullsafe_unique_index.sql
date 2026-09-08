-- ============================================================================
-- MIGRATION: Add ref.cities null-safe uniqueness index (schema-drift fix).
--
-- WHY THIS EXISTS
-- ----------------
-- job_market_intelligence_schema.sql defines only:
--   CONSTRAINT uq_cities_country_region_name UNIQUE (country_id, region_id, city_name)
-- a plain multi-column unique constraint. Under standard SQL NULL
-- semantics, two rows with the same country_id/city_name but both a NULL
-- region_id are NOT considered duplicates by this constraint -- NULL is
-- never equal to NULL, even to itself. For a country with no seeded
-- sub-regions, that means "New York, Country X, region_id=NULL" could be
-- inserted twice without violating anything.
--
-- seed/cities.py's upsert has always targeted a second, null-safe index
-- instead:
--   ON CONFLICT (country_id, COALESCE(region_id, 0), city_name)
-- which collapses NULL region_id to a fixed sentinel (0) so two such rows
-- DO correctly conflict. Confirmed against the real local database
-- (job_market_intelligence) that this index already exists there --
-- uq_cities_country_region_name_nullsafe -- alongside the original plain
-- one. It was evidently added directly to the local database at some point
-- during Step 5's original development and never made it back into
-- job_market_intelligence_schema.sql or into any migration file in this
-- repo, so every environment built from schema.sql alone (confirmed via a
-- fresh Neon database created for the cloud-scheduling migration) is
-- missing it and fails on seed.cities.seed_cities with:
--   psycopg.errors.InvalidColumnReference: there is no unique or exclusion
--   constraint matching the ON CONFLICT specification
--
-- This migration captures that already-real local index so any future
-- fresh database (a new Neon branch, a teammate's machine, CI) matches
-- what local has actually been running against all along, instead of
-- relying on an undocumented manual fix that only exists on one laptop.
--
-- WHAT THIS DOES
-- ----------------
-- Adds the null-safe index alongside the existing plain one -- does NOT
-- drop or replace uq_cities_country_region_name, matching local's actual
-- state exactly (both indexes coexist there; the plain one costs nothing
-- extra to keep and this migration's job is to mirror reality, not to
-- also decide whether the original constraint is still worth keeping).
--
-- HOW TO RUN
-- ----------------
-- Local (only needed if a fresh local DB is ever rebuilt from schema.sql
-- alone -- the current local database already has this index and running
-- this against it is a safe no-op via IF NOT EXISTS):
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f add_cities_nullsafe_unique_index.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f add_cities_nullsafe_unique_index.sql
--
-- Neon (both branches -- production is missing this index because it was
-- built from schema.sql alone; test is missing it too because it was
-- branched from production before this fix):
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" "<neon-production-connection-string>" -f add_cities_nullsafe_unique_index.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" "<neon-test-connection-string>" -f add_cities_nullsafe_unique_index.sql
-- ============================================================================

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_country_region_name_nullsafe
    ON ref.cities (country_id, COALESCE(region_id, 0), city_name);

COMMENT ON INDEX ref.uq_cities_country_region_name_nullsafe IS
    'Null-safe companion to uq_cities_country_region_name: COALESCEs region_id to 0 so two cities sharing a country_id/city_name but both having a NULL region_id (no seeded sub-region) are correctly treated as duplicates, which the plain multi-column unique constraint cannot express under standard SQL NULL semantics. seed.cities.seed_cities targets this index by name via ON CONFLICT.';

COMMIT;

-- ============================================================================
-- VERIFICATION: the index exists and the seed upsert's ON CONFLICT target
-- now resolves.
-- ============================================================================

SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'ref' AND tablename = 'cities' AND indexname = 'uq_cities_country_region_name_nullsafe';

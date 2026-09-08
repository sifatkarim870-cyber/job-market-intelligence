-- ============================================================================
-- MIGRATION: Add core.location_aliases (Step 28 — Geographic Normalization).
--
-- WHY THIS EXISTS
-- ----------------
-- Step 28 resolves each source's free-text location string
-- (CleanedJob.location_cleaned, e.g. "Remote - US", "Worldwide",
-- "Anywhere in the World; Argentina; Texas") onto a ref.locations row
-- (city/region/country + remote_work_type combo). Confirmed against the
-- real codebase before writing this: ref.locations existed in the schema
-- from day one but nothing ever wrote to it, and core.jobs.location_id has
-- been NULL on every job ever ingested.
--
-- A second, equally important confirmed fact drove this table's design:
-- CleanedJob.location_cleaned is NEVER itself persisted anywhere in the
-- schema — db.job_repository.save_cleaned_job only ever uses it as one
-- input to compute_job_content_hash, then discards it. This means
-- location resolution CANNOT run as a deferred batch job scanning
-- already-persisted core.jobs rows (the Step 25/26 company_resolution.py /
-- skill_extraction.py pattern) — by the time such a job would run, the raw
-- text it would need to resolve is already gone. Resolution therefore runs
-- INLINE from save_cleaned_job, the one point where the raw string still
-- exists in memory — see normalization/geographic_resolution.py's module
-- docstring for the fuller rationale.
--
-- core.location_aliases exists to make that inline resolution cheap and
-- auditable, mirroring core.company_aliases's role for Step 25:
--   - CACHE: job boards reuse a small set of location strings across many
--     postings. Once a (raw_location_text, source_id) pair has been
--     resolved once, every later job with the identical raw string
--     resolves via a single indexed lookup instead of re-running
--     segment-splitting + city/region/country matching queries again.
--   - AUDIT: match_method records HOW a raw string was resolved
--     ('city_exact', 'region_exact', 'country_exact', 'global_assertion',
--     or 'fallback_unmatched' — see resolve_location_text's docstring for
--     what each means), so a reviewer can later query, e.g., every raw
--     string that fell back to 'fallback_unmatched' to see whether
--     broadening ref.cities/ref.countries seed coverage would help.
--
-- This is a genuine schema addition beyond what job_market_intelligence_schema.sql
-- originally defined — flagged explicitly per this project's "schema
-- changes need sign-off before DDL" convention, confirmed with the project
-- owner as part of the Step 28 scoped proposal before this file was written.
--
-- WHAT THIS DOES
-- ----------------
-- Creates core.location_aliases, shaped identically to core.company_aliases
-- (BIGINT identity PK, UNIQUE (raw_location_text, source_id), FK to
-- ref.sources with ON DELETE SET NULL matching company_aliases's own FK
-- behavior). location_id is NOT NULL and ON DELETE CASCADE — unlike a
-- company alias (which can meaningfully exist without ever being resolved
-- to a company), a location alias row's entire reason to exist is caching
-- an already-resolved location_id; there is no partial/pending state for
-- it to survive in if the ref.locations row it points to is ever removed.
--
-- HOW TO RUN
-- ----------------
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f add_location_aliases_table.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f add_location_aliases_table.sql
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS core.location_aliases (
    location_alias_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_location_text  TEXT NOT NULL,
    source_id          SMALLINT REFERENCES ref.sources(source_id) ON UPDATE CASCADE ON DELETE SET NULL,
    location_id        BIGINT NOT NULL REFERENCES ref.locations(location_id) ON UPDATE CASCADE ON DELETE CASCADE,
    match_method        TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_location_aliases_raw_source UNIQUE (raw_location_text, source_id),
    CONSTRAINT ck_location_aliases_match_method CHECK (match_method IN
        ('city_exact', 'region_exact', 'country_exact', 'global_assertion', 'fallback_unmatched'))
);

COMMENT ON TABLE core.location_aliases IS
    'Caches raw CleanedJob.location_cleaned strings (per source, since the same text can mean different things across sources) to their resolved ref.locations.location_id, and records how the match was made (match_method) for auditability. Written to inline by normalization.geographic_resolution.resolve_and_cache_location during ingestion, NOT by a deferred batch job -- see this file''s header comment for why a batch-job pattern (like core.company_aliases) does not work here.';
COMMENT ON COLUMN core.location_aliases.match_method IS
    'How this raw string was resolved: city_exact/region_exact/country_exact (matched a seeded ref.cities/regions/countries row), global_assertion (raw text explicitly said "Worldwide"/"Anywhere"/etc.), or fallback_unmatched (nothing matched anything -- resolved to remote_global with is_global_remote=FALSE on the ref.locations row, distinguishing "unparseable" from a genuine global-remote claim).';

CREATE INDEX IF NOT EXISTS idx_location_aliases_location_id ON core.location_aliases (location_id);

-- ----------------------------------------------------------------------------
-- GRANTS
--
-- Confirmed the hard way (permission denied for table location_aliases when
-- app_user ran save_cleaned_job against a real test DB): whatever originally
-- granted app_user SELECT/INSERT on the rest of core/ref/bridge does NOT
-- automatically extend to a brand-new table created by this migration.
-- Explicit GRANTs below, matching this project's own established pattern of
-- re-granting app_user on newly-created/altered objects inside the migration
-- that creates them (see migrations/exclude_duplicates_from_active_jobs_view.sql
-- and migrations/widen_fk_columns_v3.sql doing the same for analytics views).
--
-- ref.locations is ALSO granted here, defensively, not just
-- core.location_aliases: it has existed since the original schema.sql but
-- nothing ever wrote to it before Step 28 (confirmed during this step's
-- investigation), so its INSERT privilege for app_user was never actually
-- exercised and may have the same gap. GRANT is idempotent -- safe to run
-- even if app_user already had these privileges.
-- ----------------------------------------------------------------------------
GRANT SELECT, INSERT ON core.location_aliases TO app_user;
GRANT SELECT, INSERT ON ref.locations TO app_user;

COMMIT;

-- ============================================================================
-- VERIFICATION: table exists and is queryable.
-- ============================================================================

SELECT 'core.location_aliases OK, row count:' AS check_name, count(*) FROM core.location_aliases;

-- ============================================================================
-- FOLLOW-UP (not performed by this migration, tracked here so it isn't
-- lost): pre-Step-28 jobs (every job ingested before this deploy) will
-- permanently have core.jobs.location_id = NULL. Their raw location text
-- was never stored anywhere and cannot be recovered by any batch process --
-- see normalization/geographic_resolution.py's module docstring. They will
-- only pick up a location_id if/when they are next re-scraped AND their
-- content_hash changes for some other reason (location_cleaned is already
-- part of the hash, so an unchanged location alone never triggers the
-- update path). If backfilling historical jobs' locations becomes a real
-- research need, the only fix is treating them as fresh re-scrapes at the
-- source, not something this migration or Step 28's code can do
-- retroactively.
-- ============================================================================

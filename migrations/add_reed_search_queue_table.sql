-- ============================================================================
-- MIGRATION: Add ops.reed_search_queue (Reed scraper — search query queue).
--
-- WHY THIS EXISTS
-- ----------------
-- Reed's Jobseeker API has no "give me everything" feed the way RemoteOK/
-- Remotive do — every Search call needs (or at least meaningfully narrows
-- around) keywords/locationName. scrapers/reed/search_queries.py's module
-- docstring documents this as a genuinely open design question from the
-- original Reed scoping conversation, deliberately left as ONE placeholder
-- query pending confirmation of the real production query list.
--
-- This table is that confirmed answer: a persistent, claimable queue of
-- (keywords, location_name) combinations, so ReedPipeline.run() claims a
-- budgeted number of combinations per run (ReedSettings.queries_claimed_per_run)
-- instead of reading a static in-code list, and real coverage of the UK job
-- market accumulates over many runs the same way Indeed's own
-- ops.scrape_query_queue accumulates coverage of its ~21,000 title/location
-- combinations over years.
--
-- CONFIRMED: THIS IS A SEPARATE TABLE FROM ops.scrape_query_queue, NOT A
-- SHARED ONE. The project owner explicitly asked for a separate analog
-- (2026-09-27 scoping conversation) rather than Reed sharing Indeed's own
-- table — Indeed's table is part of a separate, paused effort in this
-- repo, and its own schema (source_id + query_text + location_text +
-- last_page_reached, supporting mid-query resumption across sessions) is
-- shaped around Indeed's Selenium session model, not Reed's. Reed's own
-- pagination fully exhausts a query within one run (bounded by
-- ReedSettings.max_search_pages_per_query), so there is no cross-run
-- resumption state to track — hence no last_page_reached column here, and
-- no source_id column either (this table only ever holds Reed rows by
-- construction, unlike Indeed's genuinely multi-source-shaped table).
--
-- WHAT THIS DOES
-- ----------------
-- Creates ops.reed_search_queue: one row per (keywords, location_name)
-- combination. keywords/location_name are NOT NULL with a '' (empty
-- string) default rather than nullable TEXT columns — deliberate, so the
-- natural-key UNIQUE constraint below behaves correctly. PostgreSQL UNIQUE
-- constraints treat NULL as distinct from any other NULL (two NULLs never
-- collide), which would silently allow duplicate "no keyword filter"
-- or "no location filter" rows to accumulate; '' is a normal, comparable
-- value, so the UNIQUE constraint works as intended. db.reed_query_queue_repository.py
-- translates '' back to None when constructing a ReedSearchQuery for the
-- client to actually use — see that module's docstring.
--
-- distance_from_location deliberately does NOT participate in the natural
-- key: it is informational/override-only. Two rows cannot differ ONLY by
-- distance_from_location under this constraint — a known, accepted
-- limitation, not something the standard title x city seed needs (every
-- seeded row leaves it NULL, letting Reed apply its own default radius).
--
-- status follows the same vocabulary and "done stays eligible for
-- re-claiming" reasoning as ops.scrape_query_queue.status (see that
-- table's own COMMENT, in migrations/add_scrape_query_queue_table.sql,
-- for the full rationale — not reproduced here since this migration does
-- not depend on that one): new UK postings appear against an already-
-- searched combination over time, so a combination reaching 'done' once
-- does not mean it should never be searched again.
--
-- HOW TO RUN
-- ----------------
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f add_reed_search_queue_table.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f add_reed_search_queue_table.sql
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS ops.reed_search_queue (
    query_id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    keywords                TEXT NOT NULL DEFAULT '',
    location_name           TEXT NOT NULL DEFAULT '',
    distance_from_location  INT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    last_scraped_at         TIMESTAMPTZ,
    last_error              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_reed_search_queue_keywords_location UNIQUE (keywords, location_name),
    CONSTRAINT ck_reed_search_queue_status CHECK (status IN ('pending', 'in_progress', 'done', 'failed'))
);

COMMENT ON TABLE ops.reed_search_queue IS
    'Persistent, claimable queue of (keywords, location_name) combinations for the Reed scraper. Separate from, and NOT shared with, ops.scrape_query_queue (Indeed''s own, differently-shaped table) -- see this file''s header comment for why. ReedPipeline claims ReedSettings.queries_claimed_per_run rows per run via db.reed_query_queue_repository.ReedQueryQueueRepository.';
COMMENT ON COLUMN ops.reed_search_queue.keywords IS
    '''''  (empty string) means no keyword filter -- NOT NULL with this default so the UNIQUE constraint below behaves correctly (NULL != NULL in PostgreSQL UNIQUE semantics). Translated back to Python None by the repository layer.';
COMMENT ON COLUMN ops.reed_search_queue.location_name IS
    'Same '''' -> "no location filter" convention as keywords above.';
COMMENT ON COLUMN ops.reed_search_queue.status IS
    'pending (never claimed, or claimed but the run ended without recording a result) / in_progress (currently claimed) / done (a prior run reached the end of this query''s results) / failed (a prior run hit an unrecoverable error). pending and done are both eligible for re-claiming -- see this file''s header comment for why done does not mean permanently finished.';

CREATE INDEX IF NOT EXISTS idx_reed_search_queue_status_last_scraped
    ON ops.reed_search_queue (status, last_scraped_at);

-- ----------------------------------------------------------------------------
-- GRANTS
--
-- Following this project's established pattern (see
-- migrations/add_location_aliases_table.sql's GRANTS section): a brand-new
-- table needs its privileges granted explicitly in the same migration that
-- creates it, or app_user silently fails with permission denied the first
-- time real code touches it.
--
-- Guarded, because app_user exists on the local Postgres but NOT on Neon,
-- where you connect as the owner role (neondb_owner) and that role already
-- has full access to the table it just created. An unguarded GRANT fails
-- there with: role "app_user" does not exist -- which rolled this whole
-- migration back the first time it was run against Neon (2026-09-28).
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops.reed_search_queue TO app_user;
    ELSE
        RAISE NOTICE 'Role app_user does not exist; skipping GRANT (expected on Neon).';
    END IF;
END
$$;

COMMIT;

-- ============================================================================
-- VERIFICATION: table exists and is queryable.
-- ============================================================================

SELECT 'ops.reed_search_queue OK, row count:' AS check_name, count(*) FROM ops.reed_search_queue;

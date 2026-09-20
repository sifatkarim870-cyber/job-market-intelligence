-- ============================================================================
-- MIGRATION: Add ops.scrape_query_queue (Indeed Selenium scraper — Phase 4).
--
-- WHY THIS EXISTS
-- ----------------
-- Confirmed against the real schema before writing this: RemoteOK, Remotive,
-- and We Work Remotely each pull one flat feed per run -- there is no query
-- space to iterate, so nothing like a query queue exists anywhere in the
-- current schema (core.jobs, ops.*, or otherwise).
--
-- Indeed is different by nature of how it's being scraped: "everything
-- possible" means an indefinitely long backlog of (search term, location)
-- combinations, worked a few pages at a time, across sessions that may run
-- for years. Without a persistent queue, a run has no way to know what it
-- already covered, and a crash/block/pause has no clean resume point.
--
-- This is a genuine schema addition beyond what
-- job_market_intelligence_schema.sql originally defined -- flagged
-- explicitly per this project's "schema changes need sign-off before DDL"
-- convention (see migrations/add_location_aliases_table.sql for the
-- precedent this follows), confirmed with the project owner before this
-- file was written.
--
-- WHAT THIS DOES
-- ----------------
-- Creates ops.scrape_query_queue: one row per (source_id, query_text,
-- location_text) combination this scraper should eventually cover.
-- status tracks where that combination stands; last_page_reached lets a
-- run resume mid-query rather than restarting a large query from page 1
-- every time a session's per-run page cap is hit.
--
-- Lives in ops, not core or a new schema, because it is scraper operational
-- state -- exactly the same category job_market_intelligence_schema.sql's
-- own header already assigns to ops.scraping_sessions / ops.scraper_logs /
-- ops.failed_scrapes ("operational, not research, data").
--
-- HOW TO RUN
-- ----------------
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f add_scrape_query_queue_table.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f add_scrape_query_queue_table.sql
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS ops.scrape_query_queue (
    query_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id           SMALLINT NOT NULL REFERENCES ref.sources(source_id) ON UPDATE CASCADE ON DELETE CASCADE,
    query_text          TEXT NOT NULL,
    location_text       TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    last_page_reached   INT NOT NULL DEFAULT 0,
    last_scraped_at     TIMESTAMPTZ,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scrape_query_queue_source_query_location
        UNIQUE (source_id, query_text, location_text),
    CONSTRAINT ck_scrape_query_queue_status CHECK (status IN
        ('pending', 'in_progress', 'done', 'failed')),
    CONSTRAINT ck_scrape_query_queue_last_page_reached CHECK (last_page_reached >= 0)
);

COMMENT ON TABLE ops.scrape_query_queue IS
    'Persistent work queue of (source, search query, location) combinations for scrapers that must iterate a query space rather than pull one flat feed (Indeed being the first). A run claims the oldest eligible row, works it up to that run''s own per-session page/detail caps, and updates last_page_reached/status so the next run resumes rather than restarting. status=''done'' means the parser reached Indeed''s own last page for that combination, not that the queue item is permanently finished -- see this file''s header for why re-queuing done rows periodically is expected, not a bug.';
COMMENT ON COLUMN ops.scrape_query_queue.status IS
    'pending: not yet claimed, or claimed previously but not finished (see last_page_reached). in_progress: currently claimed by a running session -- a row stuck here past a reasonable session duration indicates a crashed run and should be manually reset to pending. done: parser reached the end of results for this combination on the last attempt. failed: session hit a hard-stop condition (CAPTCHA/challenge detected, or repeated consecutive failures) while working this row -- see last_error.';
COMMENT ON COLUMN ops.scrape_query_queue.last_page_reached IS
    'Highest search-result page number successfully parsed for this combination. A resumed run starts from last_page_reached + 1, not page 1.';

CREATE INDEX IF NOT EXISTS idx_scrape_query_queue_claim
    ON ops.scrape_query_queue (source_id, status, last_scraped_at NULLS FIRST);

CREATE TRIGGER trg_scrape_query_queue_set_updated_at
    BEFORE UPDATE ON ops.scrape_query_queue
    FOR EACH ROW EXECUTE FUNCTION system.set_updated_at();

-- ----------------------------------------------------------------------------
-- GRANTS
--
-- Following this project's own established pattern (see
-- migrations/add_location_aliases_table.sql) of re-granting app_user on
-- newly-created objects inside the migration that creates them, since that
-- privilege does not extend automatically from the rest of ops.*.
--
-- Guarded with a role-existence check rather than a bare GRANT: local
-- Postgres has an app_user role (per that same precedent), but Neon does
-- not -- Neon provisions its own owner role instead (neondb_owner in this
-- project's case), and a bare GRANT ... TO app_user fails outright with
-- "role does not exist" there, rolling back this entire transaction
-- (confirmed the hard way against production Neon before this guard was
-- added). Skipping the grant when app_user isn't present is safe: on
-- Neon, the connecting role IS the database owner already and needs no
-- separate grant to use a table it just created.
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE ON ops.scrape_query_queue TO app_user;
        GRANT USAGE, SELECT ON SEQUENCE ops.scrape_query_queue_query_id_seq TO app_user;
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- VERIFICATION: table exists and is queryable.
-- ============================================================================

SELECT 'ops.scrape_query_queue OK, row count:' AS check_name, count(*) FROM ops.scrape_query_queue;

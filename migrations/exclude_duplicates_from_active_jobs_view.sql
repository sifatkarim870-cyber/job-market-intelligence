-- ============================================================================
-- MIGRATION: Exclude detected cross-source duplicates from
-- analytics.v_active_jobs.
--
-- WHY THIS EXISTS
-- ----------------
-- Step 19 (Cross-Source Duplicate Detection) introduces a batch job that
-- sets core.jobs.is_duplicate_of on the non-canonical row of a detected
-- cross-source duplicate pair (see normalization/dedup.py). Neither
-- analytics.v_active_jobs nor analytics.job_facts have ever filtered on
-- is_duplicate_of, because the column existed in the schema from day one
-- but nothing wrote to it until now.
--
-- Left as-is, analytics.v_active_jobs would silently double-count (or
-- triple-count, etc.) any posting the dedup batch job has already
-- identified as syndicated across multiple sources -- the same underlying
-- job appearing more than once in "active jobs" figures. This migration
-- adds `AND j.is_duplicate_of IS NULL` to the view's WHERE clause so a
-- detected duplicate's non-canonical row(s) stop appearing in "active"
-- results the moment the dedup batch job runs, without deleting or
-- otherwise mutating the underlying core.jobs row (soft-exclusion only,
-- consistent with the schema's general soft-delete philosophy -- see
-- Section 1.3 of the design doc).
--
-- analytics.job_facts is intentionally NOT touched here. It is a
-- scheduled-refresh materialized view (Phase 6 territory, not yet
-- populated -- see widen_identity_columns_v2.sql's note that it has
-- almost certainly never been refreshed with real data). Its own
-- refresh definition should get the equivalent filter added when Phase 6
-- actually builds the refresh job, rather than churning it here ahead of
-- that work. Flagged in this file's tail comment so it isn't forgotten.
--
-- analytics.v_company_current_headcount_demand is also NOT touched here:
-- it does its own independent COUNT(*) FILTER over core.jobs and was
-- never in scope for this migration's stated purpose (fixing double-
-- counting through the *view most read for "what's currently open"*);
-- revisit separately if Step 19 usage shows it needs the same filter.
--
-- WHAT THIS DOES
-- ----------------
-- DROP + CREATE OR REPLACE VIEW would normally suffice for a simple
-- WHERE-clause change, but CREATE OR REPLACE VIEW cannot add a new
-- clause while keeping the same column list unless the column list is
-- literally unchanged -- which it is here, so CREATE OR REPLACE VIEW is
-- safe and used below (no DROP needed, unlike the widen_* migrations,
-- which had to change underlying column types and therefore had to drop
-- first).
--
-- Non-destructive: this only changes which rows the view returns, never
-- any row in core.jobs itself. Safe to re-run.
--
-- HOW TO RUN
-- ----------------
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f exclude_duplicates_from_active_jobs_view.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f exclude_duplicates_from_active_jobs_view.sql
-- ============================================================================

BEGIN;

CREATE OR REPLACE VIEW analytics.v_active_jobs AS
SELECT
    j.job_id,
    j.posting_date,
    j.job_title,
    c.company_name,
    l.raw_location_text,
    rwt.label   AS remote_work_type,
    et.label    AS employment_type,
    el.label    AS experience_level,
    jc.label    AS job_category,
    s.source_name,
    j.original_url,
    j.closing_date
FROM core.jobs j
JOIN core.companies c            ON c.company_id = j.company_id
JOIN ref.sources s                ON s.source_id = j.source_id
LEFT JOIN ref.locations l          ON l.location_id = j.location_id
LEFT JOIN ref.remote_work_types rwt ON rwt.remote_work_type_id = j.remote_work_type_id
LEFT JOIN ref.employment_types et    ON et.employment_type_id = j.employment_type_id
LEFT JOIN ref.experience_levels el    ON el.experience_level_id = j.experience_level_id
LEFT JOIN ref.job_categories jc        ON jc.job_category_id = j.job_category_id
WHERE j.job_status = 'active'
  AND j.is_duplicate_of IS NULL;

COMMENT ON VIEW analytics.v_active_jobs IS
    'Convenience live view (not materialized) of currently active, non-duplicate postings with human-readable lookup labels resolved. Excludes rows flagged as cross-source duplicates by the Step 19 dedup batch job (is_duplicate_of IS NOT NULL). Fine for low-QPS ad hoc queries; dashboards should hit analytics.job_facts instead.';

GRANT SELECT ON analytics.v_active_jobs TO app_user;

COMMIT;

-- ============================================================================
-- VERIFICATION: view still queryable, definition now includes the filter.
-- ============================================================================

SELECT 'v_active_jobs OK, row count:' AS check_name, count(*) FROM analytics.v_active_jobs;

SELECT pg_get_viewdef('analytics.v_active_jobs'::regclass, true) AS current_definition;

-- ============================================================================
-- FOLLOW-UP (not performed by this migration, tracked here so it isn't
-- lost): when Phase 6 builds the analytics.job_facts refresh job, add the
-- same `AND j.is_duplicate_of IS NULL` predicate to its defining query
-- before the first real REFRESH MATERIALIZED VIEW runs against production
-- data.
-- ============================================================================

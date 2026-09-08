-- ============================================================================
-- MIGRATION (v2 — corrected): Widen SMALLINT identity PKs to INT.
--
-- WHAT CHANGED FROM v1: the first attempt failed because
-- analytics.v_active_jobs (a view) and analytics.job_facts (a
-- materialized view) both depend, via JOIN conditions, on several of the
-- columns being widened. PostgreSQL refuses ALTER COLUMN TYPE on any
-- column a view's underlying query depends on until the view is dropped.
-- This version drops both dependent objects first, runs the same 12
-- ALTER TABLE statements as before, then recreates both objects EXACTLY
-- as defined in job_market_intelligence_schema.sql (Sections 14-15) —
-- same columns, same joins, same comments, same indexes.
--
-- analytics.v_company_current_headcount_demand does NOT depend on any of
-- the 12 widened columns (it only touches core.companies/core.jobs), so
-- it's left untouched — confirmed by checking its definition directly.
--
-- IMPORTANT — DATA LOSS WARNING for analytics.job_facts specifically:
-- DROP MATERIALIZED VIEW removes any data currently stored in it, not
-- just its definition. It gets recreated WITH NO DATA (identical to how
-- it was first created), so if you have EVER run
-- `REFRESH MATERIALIZED VIEW analytics.job_facts` with real data before
-- now, that computed data will be gone after this migration and you'll
-- need to refresh it again afterward:
--     REFRESH MATERIALIZED VIEW analytics.job_facts;
-- Given this project is only at Step 18 (Phase 4) and the analytics
-- layer isn't built until Phase 6, this has almost certainly never been
-- refreshed with real data yet — but check before running if you're
-- unsure, since this migration cannot recover discarded computed rows.
-- (The underlying data in core.jobs etc. is completely unaffected either
-- way — only job_facts's own derived/cached copy is at risk.)
--
-- WHY THIS MIGRATION EXISTS AT ALL: see the v1 file's header comment —
-- ref.countries.country_id's SMALLINT identity sequence hit its 32,767
-- ceiling from repeated integration-test upserts (sequences advance on
-- every attempted insert, including no-op ON CONFLICT updates, and never
-- roll back). Every other SMALLINT-identity ref.*/auth.roles table has
-- the identical exposure; this widens all twelve to INT (~2.1 billion
-- ceiling) in one pass rather than hitting this wall repeatedly, table
-- by table, over the life of the project.
--
-- SAFE TO RE-RUN: idempotent in effect. Atomic: wrapped in a single
-- transaction, so if anything unexpected fails, everything (columns AND
-- views) rolls back to exactly the pre-migration state, same as v1 just
-- demonstrated.
--
-- HOW TO RUN (same as before):
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f widen_identity_columns_v2.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f widen_identity_columns_v2.sql
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- STEP 1: Drop the view and materialized view that depend on columns
-- being widened. (v_company_current_headcount_demand is untouched — it
-- has no dependency on any of these 12 columns.)
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS analytics.v_active_jobs;
DROP MATERIALIZED VIEW IF EXISTS analytics.job_facts;

-- ---------------------------------------------------------------------------
-- STEP 2: Widen the 12 identity columns (identical to v1).
-- ---------------------------------------------------------------------------

ALTER TABLE ref.currencies        ALTER COLUMN currency_id         TYPE integer;
ALTER TABLE ref.sources           ALTER COLUMN source_id           TYPE integer;
ALTER TABLE ref.countries         ALTER COLUMN country_id          TYPE integer;
ALTER TABLE ref.remote_work_types ALTER COLUMN remote_work_type_id TYPE integer;
ALTER TABLE ref.industries        ALTER COLUMN industry_id         TYPE integer;
ALTER TABLE ref.employment_types  ALTER COLUMN employment_type_id  TYPE integer;
ALTER TABLE ref.experience_levels ALTER COLUMN experience_level_id TYPE integer;
ALTER TABLE ref.education_levels  ALTER COLUMN education_level_id  TYPE integer;
ALTER TABLE ref.job_categories    ALTER COLUMN job_category_id     TYPE integer;
ALTER TABLE ref.skill_categories  ALTER COLUMN skill_category_id   TYPE integer;
ALTER TABLE ref.languages         ALTER COLUMN language_id         TYPE integer;
ALTER TABLE auth.roles            ALTER COLUMN role_id             TYPE integer;

-- ---------------------------------------------------------------------------
-- STEP 3: Recreate analytics.v_active_jobs exactly as originally defined
-- (job_market_intelligence_schema.sql, Section 14).
-- ---------------------------------------------------------------------------

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
WHERE j.job_status = 'active';

COMMENT ON VIEW analytics.v_active_jobs IS
    'Convenience live view (not materialized) of currently active postings with human-readable lookup labels resolved. Fine for low-QPS ad hoc queries; dashboards should hit analytics.job_facts instead.';

-- Recreating this view as postgres (rather than whatever role originally
-- owned it) may reset its permissions. Re-granting SELECT to app_user
-- explicitly is a safe no-op if it already had access some other way —
-- cheap insurance against yet another permission surprise like today's
-- sequence issue, rather than finding out the hard way on the next
-- application run that queries this view.
GRANT SELECT ON analytics.v_active_jobs TO app_user;

-- ---------------------------------------------------------------------------
-- STEP 4: Recreate analytics.job_facts + its indexes exactly as
-- originally defined (job_market_intelligence_schema.sql, Section 15).
-- Recreated WITH NO DATA, same as its original creation — see the data
-- loss warning at the top of this file.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW analytics.job_facts AS
SELECT
    j.job_id,
    j.posting_date,
    j.company_id,
    c.company_name,
    nt.normalized_title,
    jc.label                              AS job_category,
    ind.industry_name                     AS industry,
    co.country_name                       AS country,
    reg.region_name                       AS region,
    ci.city_name                          AS city,
    rwt.label                             AS remote_work_type,
    et.label                              AS employment_type,
    el.label                              AS experience_level,
    edl.label                             AS education_level,
    js.normalized_annual_min_usd,
    js.normalized_annual_max_usd,
    (SELECT count(*) FROM bridge.job_skills bjs WHERE bjs.job_id = j.job_id) AS skill_count,
    (SELECT array_agg(sk.skill_name ORDER BY bjs.confidence_score DESC NULLS LAST)
       FROM bridge.job_skills bjs
       JOIN ref.skills sk ON sk.skill_id = bjs.skill_id
      WHERE bjs.job_id = j.job_id
      LIMIT 10)                           AS top_skills,
    src.source_name,
    j.job_status,
    (j.closing_date - j.posting_date)     AS days_to_fill,
    j.data_quality_score
FROM core.jobs j
JOIN core.companies c              ON c.company_id = j.company_id
JOIN ref.sources src                 ON src.source_id = j.source_id
LEFT JOIN ref.normalized_job_titles nt ON nt.normalized_title_id = j.normalized_title_id
LEFT JOIN ref.job_categories jc          ON jc.job_category_id = j.job_category_id
LEFT JOIN ref.industries ind               ON ind.industry_id = j.industry_id
LEFT JOIN ref.locations loc                  ON loc.location_id = j.location_id
LEFT JOIN ref.cities ci                        ON ci.city_id = loc.city_id
LEFT JOIN ref.regions reg                        ON reg.region_id = loc.region_id
LEFT JOIN ref.countries co                         ON co.country_id = loc.country_id
LEFT JOIN ref.remote_work_types rwt                  ON rwt.remote_work_type_id = j.remote_work_type_id
LEFT JOIN ref.employment_types et                      ON et.employment_type_id = j.employment_type_id
LEFT JOIN ref.experience_levels el                       ON el.experience_level_id = j.experience_level_id
LEFT JOIN ref.education_levels edl                         ON edl.education_level_id = j.education_level_id
LEFT JOIN salary.job_salaries js                             ON js.job_id = j.job_id
WITH NO DATA;

COMMENT ON MATERIALIZED VIEW analytics.job_facts IS
    'Wide, denormalized, scheduled-refresh fact table for dashboards/BI/ML feature input. Derived, disposable, rebuildable - never a second source of truth. Refresh nightly (or incrementally at scale) via REFRESH MATERIALIZED VIEW CONCURRENTLY, which requires the unique index below.';

CREATE UNIQUE INDEX uq_job_facts_job_id ON analytics.job_facts (job_id);
CREATE INDEX idx_job_facts_posting_date ON analytics.job_facts (posting_date);
CREATE INDEX idx_job_facts_company_id ON analytics.job_facts (company_id);
CREATE INDEX idx_job_facts_job_category ON analytics.job_facts (job_category);
CREATE INDEX idx_job_facts_country ON analytics.job_facts (country);
CREATE INDEX idx_job_facts_status ON analytics.job_facts (job_status);

-- Same reasoning as the view's re-grant above.
GRANT SELECT ON analytics.job_facts TO app_user;

COMMIT;

-- ============================================================================
-- VERIFICATION 1: confirm every widened column is now `integer`.
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

-- ============================================================================
-- VERIFICATION 2: confirm both view objects exist again and are queryable.
-- ============================================================================

SELECT 'v_active_jobs OK, row count:' AS check_name, count(*) FROM analytics.v_active_jobs;

-- Note: job_facts is WITH NO DATA, so querying it directly would raise
-- "materialized view has not been populated" rather than returning 0 —
-- checking pg_matviews.ispopulated instead avoids that false alarm.
SELECT
    'job_facts exists, ispopulated (expect false until refreshed):' AS check_name,
    ispopulated
FROM pg_matviews
WHERE schemaname = 'analytics' AND matviewname = 'job_facts';

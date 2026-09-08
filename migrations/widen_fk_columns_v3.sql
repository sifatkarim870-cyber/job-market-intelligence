-- ============================================================================
-- MIGRATION (v3): Widen every FK column that references the 12 PKs widened
-- in v2 (widen_identity_columns_v2.sql).
--
-- WHY THIS EXISTS
-- ----------------
-- v2 widened the 12 identity PK columns themselves (ref.currencies,
-- ref.sources, ref.countries, etc.) from SMALLINT to INT, on the
-- assumption that FK columns pointing at them would never need widening
-- since actual stored values stay small. That assumption was wrong:
-- ref.currencies.currency_id's identity sequence has been climbing
-- through repeated integration-test runs the entire time, exactly like
-- ref.countries.country_id did before v1/v2 — it was just never reset,
-- because only country_id's sequence got reset via fix_test_sequence.py.
-- Now that currency_id's own column is INT (from v2), it can generate a
-- value like 33990 without complaint — but every FK column pointing at
-- it (ref.countries.default_currency_id, salary.job_salaries.currency_id,
-- etc.) is STILL declared SMALLINT, so storing that value overflows them.
-- The same latent exposure exists for every other widened PK's FK
-- columns (sources, industries, job_categories, ...), since their
-- sequences have been climbing at the same rate all along, just not
-- caught yet because no test happened to push a large enough value
-- through one of those specific FK columns until now.
--
-- This migration widens every such FK column to INT, closing the gap
-- for good rather than chasing it table by table again.
--
-- WHAT THIS DOES
-- ----------------
-- Same view/materialized-view drop-and-recreate dance as v2, since
-- several of the FK columns being widened here (core.jobs.source_id,
-- core.jobs.remote_work_type_id, core.jobs.employment_type_id,
-- core.jobs.experience_level_id, core.jobs.job_category_id,
-- ref.locations.country_id) are referenced in JOIN conditions inside
-- analytics.v_active_jobs and/or analytics.job_facts, and PostgreSQL
-- blocks ALTER COLUMN TYPE on any column a view's query depends on.
-- core.jobs is RANGE partitioned; PostgreSQL 11+ propagates a parent
-- table's ALTER COLUMN TYPE to all partitions automatically, so a single
-- statement against core.jobs handles every monthly partition.
--
-- Non-destructive: existing values are all small integers well within
-- INT's range. Safe to re-run (widening a column to its current type is
-- a harmless no-op).
--
-- IMPORTANT: this does NOT need any further sequence resets. The 12 PK
-- columns already hold correct values from v2; this migration only
-- widens the columns that RECEIVE those values via foreign key.
--
-- HOW TO RUN
-- ----------------
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence_test -f widen_fk_columns_v3.sql
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d job_market_intelligence -f widen_fk_columns_v3.sql
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- STEP 1: Drop the view and materialized view (same as v2 — several FK
-- columns below are referenced in their JOIN conditions).
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS analytics.v_active_jobs;
DROP MATERIALIZED VIEW IF EXISTS analytics.job_facts;

-- ---------------------------------------------------------------------------
-- STEP 2: Widen every FK column referencing the 12 PKs widened in v2.
-- ---------------------------------------------------------------------------

ALTER TABLE ref.countries               ALTER COLUMN default_currency_id TYPE integer;
ALTER TABLE ref.regions                 ALTER COLUMN country_id          TYPE integer;
ALTER TABLE ref.cities                  ALTER COLUMN country_id          TYPE integer;
ALTER TABLE ref.locations               ALTER COLUMN country_id          TYPE integer;
ALTER TABLE ref.locations               ALTER COLUMN remote_work_type_id TYPE integer;
ALTER TABLE ref.industries              ALTER COLUMN parent_industry_id  TYPE integer;
ALTER TABLE ref.job_categories          ALTER COLUMN parent_category_id  TYPE integer;
ALTER TABLE ref.skill_categories        ALTER COLUMN parent_category_id  TYPE integer;
ALTER TABLE ref.skills                  ALTER COLUMN skill_category_id   TYPE integer;
ALTER TABLE ref.normalized_job_titles   ALTER COLUMN seniority_hint      TYPE integer;

ALTER TABLE core.companies              ALTER COLUMN primary_industry_id TYPE integer;
ALTER TABLE core.companies              ALTER COLUMN country_id          TYPE integer;
ALTER TABLE core.company_aliases        ALTER COLUMN source_id           TYPE integer;

ALTER TABLE core.jobs                   ALTER COLUMN source_id           TYPE integer;
ALTER TABLE core.jobs                   ALTER COLUMN industry_id         TYPE integer;
ALTER TABLE core.jobs                   ALTER COLUMN job_category_id     TYPE integer;
ALTER TABLE core.jobs                   ALTER COLUMN employment_type_id  TYPE integer;
ALTER TABLE core.jobs                   ALTER COLUMN experience_level_id TYPE integer;
ALTER TABLE core.jobs                   ALTER COLUMN education_level_id  TYPE integer;
ALTER TABLE core.jobs                   ALTER COLUMN remote_work_type_id TYPE integer;

ALTER TABLE bridge.company_industries   ALTER COLUMN industry_id         TYPE integer;
ALTER TABLE bridge.job_categories_map   ALTER COLUMN job_category_id     TYPE integer;
ALTER TABLE bridge.job_languages        ALTER COLUMN language_id         TYPE integer;

ALTER TABLE salary.job_salaries              ALTER COLUMN currency_id TYPE integer;
ALTER TABLE salary.salary_history            ALTER COLUMN currency_id TYPE integer;
ALTER TABLE salary.currency_exchange_rates   ALTER COLUMN currency_id TYPE integer;

ALTER TABLE ops.scraping_sessions       ALTER COLUMN source_id TYPE integer;
ALTER TABLE ops.failed_scrapes          ALTER COLUMN source_id TYPE integer;
ALTER TABLE ops.source_statistics       ALTER COLUMN source_id TYPE integer;

ALTER TABLE analytics.skill_demand_daily ALTER COLUMN country_id TYPE integer;

ALTER TABLE auth.users                  ALTER COLUMN role_id TYPE integer;

-- ---------------------------------------------------------------------------
-- STEP 3: Recreate analytics.v_active_jobs exactly as originally defined.
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

GRANT SELECT ON analytics.v_active_jobs TO app_user;

-- ---------------------------------------------------------------------------
-- STEP 4: Recreate analytics.job_facts + its indexes exactly as originally
-- defined. Recreated WITH NO DATA — see v2's data-loss note if unsure
-- whether this had ever been refreshed with real data before now.
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

GRANT SELECT ON analytics.job_facts TO app_user;

COMMIT;

-- ============================================================================
-- VERIFICATION: confirm every FK column above is now `integer`.
-- ============================================================================

SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE (table_schema, table_name, column_name) IN (
    ('ref', 'countries', 'default_currency_id'),
    ('ref', 'regions', 'country_id'),
    ('ref', 'cities', 'country_id'),
    ('ref', 'locations', 'country_id'),
    ('ref', 'locations', 'remote_work_type_id'),
    ('ref', 'industries', 'parent_industry_id'),
    ('ref', 'job_categories', 'parent_category_id'),
    ('ref', 'skill_categories', 'parent_category_id'),
    ('ref', 'skills', 'skill_category_id'),
    ('ref', 'normalized_job_titles', 'seniority_hint'),
    ('core', 'companies', 'primary_industry_id'),
    ('core', 'companies', 'country_id'),
    ('core', 'company_aliases', 'source_id'),
    ('core', 'jobs', 'source_id'),
    ('core', 'jobs', 'industry_id'),
    ('core', 'jobs', 'job_category_id'),
    ('core', 'jobs', 'employment_type_id'),
    ('core', 'jobs', 'experience_level_id'),
    ('core', 'jobs', 'education_level_id'),
    ('core', 'jobs', 'remote_work_type_id'),
    ('bridge', 'company_industries', 'industry_id'),
    ('bridge', 'job_categories_map', 'job_category_id'),
    ('bridge', 'job_languages', 'language_id'),
    ('salary', 'job_salaries', 'currency_id'),
    ('salary', 'salary_history', 'currency_id'),
    ('salary', 'currency_exchange_rates', 'currency_id'),
    ('ops', 'scraping_sessions', 'source_id'),
    ('ops', 'failed_scrapes', 'source_id'),
    ('ops', 'source_statistics', 'source_id'),
    ('analytics', 'skill_demand_daily', 'country_id'),
    ('auth', 'users', 'role_id')
)
ORDER BY table_schema, table_name, column_name;

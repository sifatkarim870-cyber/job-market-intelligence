-- ============================================================================
-- MIGRATION: Add title-classification tracking columns to core.jobs (Step 29).
--
-- WHY THESE COLUMNS, NOT A REUSE OF EXISTING ONES
-- ------------------------------------------------
-- core.jobs.data_quality_score already exists and might look like a fit for
-- "is this a real job posting" -- it explicitly is NOT. Its own docstring in
-- cleaning/remoteok_cleaner.py states: "this is not, and should not become,
-- a spam/junk-content classifier" -- it measures field *completeness*, a
-- different concept from content *validity*. Confirmed by reading that code
-- before adding anything here, rather than assuming data_quality_score could
-- be repurposed.
--
-- Mirrors bridge.job_skills' existing confidence_score/extracted_by
-- provenance pattern -- this project's established convention for "let an
-- automated process attach a labeled, confidence-scored judgment" -- rather
-- than inventing a new shape.
--
-- Three distinguishable outcomes this enables:
--   1. normalized_title_id IS NOT NULL, status='matched'        -> success
--   2. normalized_title_id IS NULL,     status='no_match'       -> real job,
--      doesn't fit the current curated taxonomy (a signal the taxonomy may
--      need expanding, not a data problem)
--   3. normalized_title_id IS NULL,     status='excluded_non_job' -> confirmed
--      non-job content (test entries, personal bios, blog posts, benefits
--      listings -- confirmed as the majority case for RemoteOK's noise
--      titles by real sampling before this migration was written)
--
-- status='excluded_non_job' is deliberately a NEW column, not an extension of
-- job_status's existing CHECK constraint (active/closed/expired/removed/
-- filled) -- job_status is lifecycle state for a real posting; "this was
-- never a real posting at all" is a different concept and conflating them
-- would make every future job_status query need to remember to filter out
-- non-jobs too.
-- ============================================================================

BEGIN;

ALTER TABLE core.jobs
    ADD COLUMN IF NOT EXISTS title_classification_status TEXT,
    ADD COLUMN IF NOT EXISTS normalized_title_confidence  NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS title_classified_by          TEXT;

ALTER TABLE core.jobs
    ADD CONSTRAINT ck_jobs_title_classification_status CHECK (
        title_classification_status IS NULL
        OR title_classification_status IN ('matched', 'no_match', 'excluded_non_job')
    );

ALTER TABLE core.jobs
    ADD CONSTRAINT ck_jobs_normalized_title_confidence CHECK (
        normalized_title_confidence IS NULL
        OR normalized_title_confidence BETWEEN 0 AND 1
    );

COMMENT ON COLUMN core.jobs.title_classification_status IS
    'Outcome of the Step 29 title-classification batch job: matched (normalized_title_id set), no_match (real job, taxonomy needs expanding), or excluded_non_job (confirmed non-job content -- test entries, bios, blog posts, benefit listings). NULL = not yet classified.';
COMMENT ON COLUMN core.jobs.normalized_title_confidence IS
    'Cosine-similarity score (0-1) from the embedding-based match against ref.normalized_job_titles, mirroring bridge.job_skills.confidence_score''s provenance pattern.';
COMMENT ON COLUMN core.jobs.title_classified_by IS
    'Provenance label, e.g. embedding:paraphrase-multilingual-MiniLM-L12-v2:v1 -- mirrors bridge.job_skills.extracted_by''s convention of labeling method + model/version.';

GRANT SELECT, UPDATE (normalized_title_id, title_classification_status, normalized_title_confidence, title_classified_by)
    ON core.jobs TO app_user;

COMMIT;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'core' AND table_name = 'jobs'
  AND column_name IN ('title_classification_status', 'normalized_title_confidence', 'title_classified_by')
ORDER BY column_name;

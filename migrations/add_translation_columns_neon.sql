-- NEON VARIANT of add_translation_columns.sql.
--
-- SKIPPED ON NEON: GRANT SELECT, UPDATE (language_code, job_title_en, translated_by)
--     ON core.jobs TO app_user;
-- SKIPPED ON NEON: GRANT SELECT, UPDATE (description_en)
--     ON core.job_descriptions TO app_user;
--     (no app_user role exists on Neon; neondb_owner already owns every object
--      in this database, so no equivalent grant is needed there.)
--
-- See the main migration's header for the full rationale; identical
-- column definitions and comments below.

BEGIN;

ALTER TABLE core.jobs
    ADD COLUMN IF NOT EXISTS language_code TEXT,
    ADD COLUMN IF NOT EXISTS job_title_en  TEXT,
    ADD COLUMN IF NOT EXISTS translated_by TEXT;

ALTER TABLE core.job_descriptions
    ADD COLUMN IF NOT EXISTS description_en TEXT;

COMMENT ON COLUMN core.jobs.language_code IS
    'Detected source language of job_title/description (ISO 639-1 lowercase, or "unknown"). Non-NULL = the translation batch has processed this row (its idempotency marker). "en" = English original, nothing translated.';
COMMENT ON COLUMN core.jobs.job_title_en IS
    'English translation of job_title produced by the translation batch (scripts/run_translation_batch.py). NULL for English originals (COALESCE with job_title) and for pending/failed rows -- additive only, the original job_title is never modified.';
COMMENT ON COLUMN core.jobs.translated_by IS
    'Provenance label, e.g. translation:nllb-200-distilled-600M:v1 -- mirrors title_classified_by/extracted_by conventions. NULL for English rows (detected, not translated).';
COMMENT ON COLUMN core.job_descriptions.description_en IS
    'English translation of description_clean from the translation batch. NULL for English originals (COALESCE with description_clean) and for pending rows.';

COMMIT;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'core'
  AND ((table_name = 'jobs' AND column_name IN ('language_code', 'job_title_en', 'translated_by'))
    OR (table_name = 'job_descriptions' AND column_name = 'description_en'))
ORDER BY table_name, column_name;

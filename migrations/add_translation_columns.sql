-- ============================================================================
-- MIGRATION: Add translation columns (language_code + English translations).
--
-- WHY (confirmed need, 2026-10-05)
-- --------------------------------
-- Every downstream enrichment in this project speaks English:
--   * ref.normalized_job_titles taxonomy (2,046 entries, 0 non-Latin) that
--     title classification embeds against;
--   * ref.skills vocabulary (461 entries) that skill extraction scans for;
--   * the "translate before classification" pipeline decision the project
--     adopted for the multilingual scraper queue (Persian, Korean, Ukrainian,
--     Spanish, Chinese, Armenian ... sites still to be added).
-- Non-English sources so far got by on the multilingual embedding model
-- alone, with real false positives visible in 51job data (a Chinese
-- "quality engineer" title matching "MLOps Engineer" at 0.77 confidence) and
-- a skill-extraction yield of only 20% on Chinese descriptions versus
-- ~85% project-wide on English. Translating once, at rest, fixes both
-- consumers with one artifact -- see normalization/translation.py.
--
-- SHAPE
-- -----
--   core.jobs.language_code       detected source language (ISO 639-1
--                                 lowercase, or 'unknown'); non-NULL is the
--                                 batch's processed marker, so re-runs are
--                                 naturally idempotent without a second
--                                 bookkeeping column.
--   core.jobs.job_title_en        English title. NULL for English originals
--                                 (honest absence: nothing was translated --
--                                 consumers COALESCE with job_title) and for
--                                 rows whose translation is still pending.
--   core.jobs.translated_by       provenance label, mirroring
--                                 title_classified_by / bridge.job_skills
--                                 .extracted_by ("labelled method + model +
--                                 version" convention). NULL for English
--                                 rows -- they were detected, not
--                                 translated.
--   core.job_descriptions.description_en  English description; same NULL
--                                 convention as job_title_en.
--
-- Translation is deliberately a separate batch (scripts/
-- run_translation_batch.py), never part of any scraper pipeline: a model
-- download or inference failure must not block ingestion, and the raw
-- stored text stays untouched -- translations are additive columns.
-- ============================================================================

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

GRANT SELECT, UPDATE (language_code, job_title_en, translated_by)
    ON core.jobs TO app_user;

GRANT SELECT, UPDATE (description_en)
    ON core.job_descriptions TO app_user;

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

"""
Entity resolution and normalization: company alias matching, cross-source duplicate detection,
skill extraction/mapping, salary/currency normalization, geographic resolution, and job-title
canonicalization. (Built starting Step 10b, deepened in Phase 5.)

Step 19 (Cross-Source Duplicate Detection) was the first business logic to
land in this package — see ``dedup.py`` for the conservative
title+company+date-window matching strategy and ``config.py`` for its
tunable settings. Step 25 (Company Resolution) is the second — see
``company_resolution.py`` for the pg_trgm-similarity candidate-generation
batch job (never auto-merges; writes proposed aliases to
``core.company_aliases`` for human review via
``scripts/review_company_aliases.py``). Step 26 (Skill Extraction) is the
third — see ``skill_extraction.py`` for the description-text keyword-scan
batch job (matches against the curated ``ref.skills`` vocabulary; never
auto-creates new skills). Salary/currency normalization (Step 27) is the
fourth — see ``salary_standardization.py`` for the pay-period/currency
annualization function. Unlike the three batch jobs above, it runs
inline from ``db.job_repository.save_cleaned_job`` rather than as a
separate batch script, since every input it needs is already available
at ingestion time (see that module's docstring for why). Geographic
resolution (Step 28) is the fifth -- see ``geographic_resolution.py`` for
the segment-splitting, exact-match-against-seeded-reference-data
resolver. It ALSO runs inline from ``save_cleaned_job``, for a stronger
reason than salary's: ``CleanedJob.location_cleaned`` is never persisted
anywhere in the schema, so a deferred batch job (the Step 25/26 pattern)
would have nothing left to resolve once a job is already stored -- see
that module's docstring for the full, confirmed-against-real-code
rationale. Job-title / occupation classification (Step 29) is the sixth
-- see ``title_classification.py`` for the local multilingual
sentence-embedding batch job (matches against the curated
``ref.normalized_job_titles`` taxonomy; never invents new canonical
titles). Deliberately uses two separate signals rather than one:
embedding similarity decides matched/no_match, a narrow deny-list
heuristic decides excluded_non_job -- see that module's docstring for
why those are different questions embedding similarity alone can't
answer together.
"""

from job_market_intel.normalization.company_resolution import (
    CompanyAliasCandidate,
    CompanyRecord,
    apply_alias_candidates,
    build_alias_candidates,
    fetch_alias_candidate_pairs,
    reject_alias_candidates,
    run_company_resolution_batch,
    strip_corporate_suffixes,
)
from job_market_intel.normalization.config import (
    CompanyResolutionSettings,
    DedupSettings,
    get_company_resolution_settings,
    get_dedup_settings,
)
from job_market_intel.normalization.dedup import (
    DuplicateMatch,
    JobDedupRecord,
    apply_duplicate_matches,
    fetch_dedup_candidates,
    find_duplicate_matches,
    normalize_for_matching,
    run_dedup_batch,
)
from job_market_intel.normalization.geographic_resolution import (
    ResolvedLocation,
    get_or_create_location,
    resolve_and_cache_location,
    resolve_location_text,
    split_location_segments,
)
from job_market_intel.normalization.salary_standardization import (
    normalize_annual_salary,
)
from job_market_intel.normalization.skill_extraction import (
    DEFAULT_EXTRACTED_BY,
    JobDescriptionRecord,
    SkillVocabularyEntry,
    apply_skill_extractions,
    build_term_index,
    extract_skill_ids,
    fetch_skill_vocabulary,
    fetch_unscanned_jobs,
    normalize_skill_term,
    run_skill_extraction_batch,
)
from job_market_intel.normalization.title_classification import (
    DEFAULT_CLASSIFIED_BY,
    ClassificationResult,
    TaxonomyEntry,
    UnclassifiedJob,
    apply_classification,
    build_embedding_text,
    classify_job,
    fetch_taxonomy,
    fetch_unclassified_jobs,
    looks_like_non_job_content,
    run_title_classification_batch,
    strip_boilerplate,
)
from job_market_intel.normalization.translation import (
    DEFAULT_TRANSLATED_BY,
    NllbTranslator,
    TranslationJob,
    TranslationSettings,
    apply_description_translation,
    apply_title_translation,
    choose_detection_text,
    detect_language,
    fetch_description_pending,
    fetch_detection_pending,
    process_description_row,
    process_detection_row,
    resolve_flores_code,
    split_into_chunks,
)

__all__ = [
    "DEFAULT_CLASSIFIED_BY",
    "DEFAULT_EXTRACTED_BY",
    "DEFAULT_TRANSLATED_BY",
    "ClassificationResult",
    "CompanyAliasCandidate",
    "CompanyRecord",
    "CompanyResolutionSettings",
    "DedupSettings",
    "DuplicateMatch",
    "JobDedupRecord",
    "JobDescriptionRecord",
    "NllbTranslator",
    "ResolvedLocation",
    "SkillVocabularyEntry",
    "TaxonomyEntry",
    "TranslationJob",
    "TranslationSettings",
    "UnclassifiedJob",
    "apply_alias_candidates",
    "apply_classification",
    "apply_description_translation",
    "apply_duplicate_matches",
    "apply_skill_extractions",
    "apply_title_translation",
    "build_alias_candidates",
    "build_embedding_text",
    "build_term_index",
    "choose_detection_text",
    "classify_job",
    "detect_language",
    "extract_skill_ids",
    "fetch_alias_candidate_pairs",
    "fetch_dedup_candidates",
    "fetch_description_pending",
    "fetch_detection_pending",
    "fetch_skill_vocabulary",
    "fetch_taxonomy",
    "fetch_unclassified_jobs",
    "fetch_unscanned_jobs",
    "find_duplicate_matches",
    "get_company_resolution_settings",
    "get_dedup_settings",
    "get_or_create_location",
    "looks_like_non_job_content",
    "normalize_annual_salary",
    "normalize_for_matching",
    "normalize_skill_term",
    "process_description_row",
    "process_detection_row",
    "reject_alias_candidates",
    "resolve_and_cache_location",
    "resolve_flores_code",
    "resolve_location_text",
    "run_company_resolution_batch",
    "run_dedup_batch",
    "run_skill_extraction_batch",
    "run_title_classification_batch",
    "split_into_chunks",
    "split_location_segments",
    "strip_boilerplate",
    "strip_corporate_suffixes",
]

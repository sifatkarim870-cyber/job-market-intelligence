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
rationale. Job-title canonicalization remains scaffolding-only until its
later step.
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
from job_market_intel.normalization.salary_standardization import normalize_annual_salary
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

__all__ = [
    "DEFAULT_EXTRACTED_BY",
    "CompanyAliasCandidate",
    "CompanyRecord",
    "CompanyResolutionSettings",
    "DedupSettings",
    "DuplicateMatch",
    "JobDedupRecord",
    "JobDescriptionRecord",
    "ResolvedLocation",
    "SkillVocabularyEntry",
    "apply_alias_candidates",
    "apply_duplicate_matches",
    "apply_skill_extractions",
    "build_alias_candidates",
    "build_term_index",
    "extract_skill_ids",
    "fetch_alias_candidate_pairs",
    "fetch_dedup_candidates",
    "fetch_skill_vocabulary",
    "fetch_unscanned_jobs",
    "find_duplicate_matches",
    "get_company_resolution_settings",
    "get_dedup_settings",
    "get_or_create_location",
    "normalize_annual_salary",
    "normalize_for_matching",
    "normalize_skill_term",
    "reject_alias_candidates",
    "resolve_and_cache_location",
    "resolve_location_text",
    "run_company_resolution_batch",
    "run_dedup_batch",
    "run_skill_extraction_batch",
    "split_location_segments",
    "strip_corporate_suffixes",
]

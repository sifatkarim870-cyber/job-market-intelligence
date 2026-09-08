"""Skill extraction from job description text (Step 26).

How this step's scope got here (investigated, not assumed): the original
plan was to persist each source's already-cleaned tag list
(``CleanedJob.skills``) onto ``bridge.job_skills``. Investigation before
writing any code found that gap doesn't actually exist where expected --
``CleanedJob.skills`` is never written anywhere by
``JobRepository.save_cleaned_job``, and neither is ``CleanedJob.raw_payload``
(``core.jobs.raw_html_ref`` exists in the schema for this but nothing
writes to it either). Once a separate *batch* job was chosen (rather than
inline extraction during ingestion), that made the gap fatal: a batch job
run after ingestion has nothing to scan, since the tags are already gone
by the time it runs. The resolution, confirmed before writing this
module: extract skills by scanning ``core.job_descriptions.description_clean``
instead -- that column IS already persisted by ``save_cleaned_job`` on
both insert and update, so a batch job scanning it has real data.

Matching strategy
------------------
For every ``ref.skills`` row, every one of its match terms (the
``skill_name`` itself, normalized, plus each entry in ``aliases``) is
compiled into one of two patterns:

    - **Long terms** (> 2 characters, most of the vocabulary): matched
      case-insensitively.
    - **Short/ambiguous terms** (<= 2 characters after normalization --
      e.g. "R", "C", "Go", "js"): matched *case-sensitively*, since
      lowercase "go" and "r" collide constantly with ordinary English
      ("go the extra mile", pronouns) and would produce enormous
      false-positive rates if matched case-insensitively.

Both patterns use a boundary check based on "not immediately preceded/
followed by a letter or digit" rather than regex ``\\b``, because ``\\b``
silently breaks for terms ending in punctuation: ``\\bC\\+\\+\\b`` fails to
match "C++." (trailing period) since ``\\b`` requires a transition between
a word character and a non-word character, and "+" and "." are *both*
non-word characters -- no transition exists there. This affects several
terms already in the seeded vocabulary: C++, C#, Node.js, ASP.NET,
Vue.js, Next.js, Express.js. The custom boundary used here checks purely
for letters/digits on either side, so it holds regardless of what
punctuation (if any) borders the term.

The short/ambiguous pattern goes one step further: even case-sensitive
"R" alone doesn't stop the single most common real false positive, "R&D"
-- "R&D" is conventionally capitalized, so a case-sensitive match for
"R" still hits it. The short-term boundary additionally excludes ``&``,
``-``, and ``/`` as valid boundary characters (on top of letters/digits),
so "R&D" can't match "R" while "experience in R" or "using R for stats"
still can.

What this module deliberately does NOT do:
    - Auto-create new ``ref.skills`` rows for text that doesn't match the
      curated vocabulary. That idea came from an earlier tag-list-based
      design ("this raw tag didn't match anything, create a skill for
      it") and doesn't translate to keyword-scanning: there's no
      discrete "unmatched tag" to create a skill from when you're
      searching free text for occurrences of skills you already know
      about. The vocabulary only grows via curated seeding
      (``seed/skills.py``), not automatically from this module.
    - Scan ``core.jobs.job_title`` -- scope is ``description_clean``
      only, per the confirmed decision. Title-scanning is a plausible
      future enhancement, not built here.
    - Distinguish "required" vs "preferred" skills. Free-text keyword
      matching has no reliable signal for this distinction, so every
      match is recorded with ``requirement_type='required'`` (a
      confirmed simplification, not an inferred judgment).
    - Track "this job was scanned and had zero matching skills" as
      distinct from "this job hasn't been scanned yet" -- both look
      identical (no ``bridge.job_skills`` row with this module's
      ``extracted_by`` label), so a job with a genuinely skill-free
      description gets rescanned on every batch run. Wasteful at scale,
      not incorrect (rescanning just reproduces the same empty result).
      Flagged here rather than solved with additional schema for this
      first version.

``confidence_score`` is recorded as 1.0 for every match -- it reflects
"the matched substring exactly equals a known vocabulary term," not "we
are certain this job truly requires this skill." Free-text scanning,
even with the mitigations above, is not the same certainty level as an
exact tag-list lookup would have been; 1.0 is a modeling simplification
for this first version, easy to revisit if review of real matches
surfaces a reason to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

#: Terms at or below this length (after normalization) are treated as
#: short/ambiguous -- see the module docstring's "Matching strategy".
_SHORT_TERM_MAX_LENGTH = 2

#: Default extracted_by label for job_skills rows this module writes.
#: Versioned (``_v1``) per the schema's own documented convention for
#: this column ("rule_based, model version") -- change the version
#: suffix, not this module's matching logic in place, if the matching
#: strategy changes in a way that should be distinguishable in the data
#: from earlier runs.
DEFAULT_EXTRACTED_BY = "rule_based:description_keyword_scan_v1"

#: Characters that do NOT count as a valid boundary for the general
#: (long-term) pattern: matching stops only at letters/digits, so terms
#: ending in punctuation (C++, C#, Node.js) still match correctly next
#: to normal sentence punctuation.
_GENERAL_BOUNDARY_BLOCK = "A-Za-z0-9"

#: Characters that do NOT count as a valid boundary for the short/
#: ambiguous-term pattern: letters/digits PLUS &, -, / -- specifically
#: to stop "R&D" from matching skill "R". See module docstring.
_SHORT_BOUNDARY_BLOCK = "A-Za-z0-9&\\-/"


@dataclass(frozen=True)
class SkillVocabularyEntry:
    """One ``ref.skills`` row, with its match terms not yet split into
    short/long -- see ``build_term_index``.
    """

    skill_id: int
    skill_name: str
    normalized_skill_name: str
    aliases: list[str]


def normalize_skill_term(raw: str) -> str:
    """Lower-case, strip, collapse internal whitespace.

    Deliberately NOT ``normalization.dedup.normalize_for_matching``,
    which additionally strips punctuation noise (``.,-_/\\'"()&``) --
    fine for job titles/company names, but would corrupt matching here:
    ``ref.skills.normalized_skill_name`` was computed at seed time
    (``seed/utils.normalize_name``) WITHOUT punctuation stripping, so
    "Node.js" stayed "node.js", not "nodejs". Reusing dedup's version
    would make this function disagree with the very vocabulary it's
    supposed to match against, for exactly the skills most likely to
    contain matching-relevant punctuation (Node.js, C++, C#, ASP.NET,
    scikit-learn, Vue.js, Next.js, Express.js). This function matches
    ``seed/utils.normalize_name`` exactly instead -- duplicated rather
    than imported, since ``seed/`` is a standalone top-level package
    (only ``src/job_market_intel`` is built per ``pyproject.toml``), not
    something runtime library code can safely import from.
    """
    return " ".join(raw.strip().lower().split())


def fetch_skill_vocabulary(session: Session) -> list[SkillVocabularyEntry]:
    """Fetches every ``ref.skills`` row for term-index building."""
    rows = session.execute(
        text("SELECT skill_id, skill_name, normalized_skill_name, aliases FROM ref.skills")
    ).all()

    return [
        SkillVocabularyEntry(
            skill_id=row.skill_id,
            skill_name=row.skill_name,
            normalized_skill_name=row.normalized_skill_name,
            aliases=list(row.aliases or []),
        )
        for row in rows
    ]


def build_term_index(
    vocabulary: list[SkillVocabularyEntry],
) -> tuple[dict[str, int], dict[str, int]]:
    """Splits every vocabulary entry's match terms (its
    ``normalized_skill_name`` plus each alias) into short/long buckets.

    Pure Python, no session -- directly unit-testable against synthetic
    ``SkillVocabularyEntry`` lists.

    Returns:
        ``(short_terms, long_terms)`` -- each a dict mapping a match
        term to its ``skill_id``. ``short_terms`` keys keep their
        original casing (case-sensitive matching needs exact case);
        ``long_terms`` keys are lowercased (matched case-insensitively,
        so the stored case doesn't matter for lookup, only for display
        elsewhere).
    """
    short_terms: dict[str, int] = {}
    long_terms: dict[str, int] = {}

    for entry in vocabulary:
        candidate_terms = [entry.skill_name, *entry.aliases]

        for raw_term in candidate_terms:
            normalized = normalize_skill_term(raw_term)
            if not normalized:
                continue

            if len(normalized) <= _SHORT_TERM_MAX_LENGTH:
                # Short/ambiguous: keep original (pre-lowercasing) case
                # from the vocabulary for exact case-sensitive matching.
                short_terms[raw_term.strip()] = entry.skill_id
            else:
                long_terms[normalized] = entry.skill_id

    return short_terms, long_terms


def _compile_boundary_pattern(
    terms: list[str], block_chars: str, case_sensitive: bool
) -> re.Pattern[str] | None:
    """Builds one compiled alternation pattern matching any of `terms`,
    each bounded by "not immediately preceded/followed by a character in
    `block_chars`" instead of ``\\b`` -- see module docstring for why.

    Returns None if `terms` is empty (nothing to compile) -- callers
    must handle this (an empty vocabulary, or a vocabulary with no
    short/no long terms, is a valid state, not an error).
    """
    if not terms:
        return None

    # Longest-first: with alternation, Python's re tries alternatives in
    # order and takes the first that matches at a given position, not
    # the longest. Without this ordering, a short term that happens to
    # be a prefix of a longer one (e.g. hypothetically "go" before
    # "gorilla-something") could win by appearing first in an
    # unordered dict. All of this module's real vocabulary terms are
    # independent match targets for different skills, so this is
    # precautionary correctness, not a fix for an observed bug.
    ordered = sorted(terms, key=len, reverse=True)
    alternation = "|".join(re.escape(term) for term in ordered)

    pattern = rf"(?<![{block_chars}])(?:{alternation})(?![{block_chars}])"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def extract_skill_ids(
    description_text: str,
    short_terms: dict[str, int],
    long_terms: dict[str, int],
) -> set[int]:
    """Scans `description_text` for occurrences of any vocabulary term,
    returning the set of matched ``skill_id`` values.

    Pure Python, no session -- directly unit-testable, including the
    specific false-positive regression cases this module exists to
    avoid (e.g. "R&D" must NOT match skill "R").

    Args:
        description_text: ``core.job_descriptions.description_clean``
            for one job. Original casing must be preserved (the cleaners
            don't lowercase this field) -- case-sensitive short-term
            matching depends on it.
        short_terms: From ``build_term_index`` -- case-sensitive,
            strict-boundary matching.
        long_terms: From ``build_term_index`` -- case-insensitive,
            general-boundary matching.
    """
    if not description_text:
        return set()

    matched: set[int] = set()

    short_pattern = _compile_boundary_pattern(
        list(short_terms.keys()), _SHORT_BOUNDARY_BLOCK, case_sensitive=True
    )
    if short_pattern is not None:
        for match in short_pattern.finditer(description_text):
            matched.add(short_terms[match.group(0)])

    long_pattern = _compile_boundary_pattern(
        list(long_terms.keys()), _GENERAL_BOUNDARY_BLOCK, case_sensitive=False
    )
    if long_pattern is not None:
        for match in long_pattern.finditer(description_text):
            matched.add(long_terms[match.group(0).lower()])

    return matched


@dataclass(frozen=True)
class JobDescriptionRecord:
    """One job pending skill extraction."""

    job_id: int
    posting_date: object  # date -- see note in fetch_unscanned_jobs
    description_clean: str


def fetch_unscanned_jobs(
    session: Session, extracted_by_label: str = DEFAULT_EXTRACTED_BY
) -> list[JobDescriptionRecord]:
    """Fetches jobs with a description but no ``bridge.job_skills`` rows
    from this extractor yet.

    A job that was already scanned and genuinely had zero matching
    skills looks identical to one never scanned (see module docstring's
    "zero matching skills" limitation) -- both get re-selected here.
    Wasteful at scale, not incorrect: re-running extraction on an
    already-processed job with matches is a safe no-op via
    ``apply_skill_extractions``'s ``ON CONFLICT DO NOTHING``.
    """
    rows = session.execute(
        text(
            "SELECT j.job_id, j.posting_date, jd.description_clean "
            "FROM core.jobs j "
            "JOIN core.job_descriptions jd ON jd.job_id = j.job_id "
            "WHERE jd.description_clean IS NOT NULL "
            "AND NOT EXISTS ( "
            "  SELECT 1 FROM bridge.job_skills bjs "
            "  WHERE bjs.job_id = j.job_id AND bjs.extracted_by = :extracted_by "
            ")"
        ),
        {"extracted_by": extracted_by_label},
    ).all()

    return [
        JobDescriptionRecord(
            job_id=row.job_id,
            posting_date=row.posting_date,
            description_clean=row.description_clean,
        )
        for row in rows
    ]


def apply_skill_extractions(
    session: Session,
    job_id: int,
    posting_date: object,
    skill_ids: set[int],
    extracted_by_label: str = DEFAULT_EXTRACTED_BY,
) -> int:
    """Inserts one ``bridge.job_skills`` row per matched skill for one
    job. ``requirement_type`` is always ``'required'`` (confirmed
    simplification -- see module docstring), ``confidence_score`` always
    1.0.

    ``ON CONFLICT (job_id, skill_id, requirement_type) DO NOTHING`` makes
    this naturally idempotent -- safe to call again for a job that
    already has some or all of these associations.

    Does not commit -- caller's/unit-of-work's responsibility, matching
    every other write function in this project.

    Returns:
        Number of rows actually inserted (excludes rows skipped by the
        conflict target).
    """
    inserted = 0

    for skill_id in skill_ids:
        result = session.execute(
            text(
                "INSERT INTO bridge.job_skills "
                "(job_id, posting_date, skill_id, requirement_type, "
                "confidence_score, extracted_by) "
                "VALUES (:job_id, :posting_date, :skill_id, 'required', 1.0, :extracted_by) "
                "ON CONFLICT (job_id, skill_id, requirement_type) DO NOTHING"
            ),
            {
                "job_id": job_id,
                "posting_date": posting_date,
                "skill_id": skill_id,
                "extracted_by": extracted_by_label,
            },
        )
        # Same documented mypy deviation as normalization.dedup and
        # normalization.company_resolution: session.execute() is typed
        # as the generic Result[Any], which has no `.rowcount` in its
        # stub, though the CursorResult a raw INSERT actually returns
        # at runtime does.
        if result.rowcount:  # type: ignore[attr-defined]
            inserted += 1

    return inserted


def run_skill_extraction_batch(
    session: Session, extracted_by_label: str = DEFAULT_EXTRACTED_BY
) -> dict[str, int]:
    """End-to-end batch run: fetch the vocabulary once, build the term
    index and patterns once, then scan every not-yet-scanned job.

    This is the single entry point ``scripts/run_skill_extraction_batch.py``
    calls. Does not commit (caller's unit of work).

    Returns:
        Dict with keys ``jobs_scanned``, ``skill_associations_created``.
    """
    vocabulary = fetch_skill_vocabulary(session)
    short_terms, long_terms = build_term_index(vocabulary)

    jobs = fetch_unscanned_jobs(session, extracted_by_label=extracted_by_label)

    associations_created = 0
    for job in jobs:
        skill_ids = extract_skill_ids(job.description_clean, short_terms, long_terms)
        if skill_ids:
            associations_created += apply_skill_extractions(
                session,
                job_id=job.job_id,
                posting_date=job.posting_date,
                skill_ids=skill_ids,
                extracted_by_label=extracted_by_label,
            )

    logger.info(
        "Skill extraction batch: {} jobs scanned, {} skill association(s) created.",
        len(jobs),
        associations_created,
    )

    return {
        "jobs_scanned": len(jobs),
        "skill_associations_created": associations_created,
    }

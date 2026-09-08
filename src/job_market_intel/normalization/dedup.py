"""Cross-source duplicate detection (Step 19).

Where this fits: same syndication problem the design doc calls out in
Section 5.6 ("N:1 to companies... `is_duplicate_of` points to canonical
job_id if this row is a detected duplicate posted across sources") and
the schema's own comment on ``core.jobs.is_duplicate_of`` ("referential
integrity for this column is enforced by the ingestion/dedup pipeline,
not the database"). This module *is* that pipeline.

What this deliberately is NOT (confirmed against the current codebase
before writing a line of this, not assumed):

    - NOT company resolution (Step 25). ``core.company_aliases`` exists
      in the schema but is written to and read from nowhere in the
      codebase today — it is inert scaffolding, not an active alias
      table this module can lean on. ``core.companies.normalized_name``
      matching in ``db.job_repository.get_or_create_company`` is
      case-insensitive exact-string matching only, with no fuzzy/alias
      resolution behind it. This module's own company-name normalization
      (below) is therefore doing real work, not delegating to an
      existing resolver.
    - NOT geographic normalization (Step 28). ``location_cleaned`` is
      still a raw per-source string on every ``CleanedJob``
      (``cleaning/common.py`` says so explicitly) — this module does not
      use location as a matching signal at all for that reason; two
      genuinely-identical postings could have differently-formatted
      location strings today through no fault of either source.
    - NOT inline/at-insert-time detection. Confirmed design decision:
      this runs as a separate batch job (``scripts/run_dedup_batch.py``),
      after ingestion, scanning already-persisted ``core.jobs`` rows —
      not from inside ``db.job_repository.save_cleaned_job``.

Matching strategy (confirmed design decision: conservative, not fuzzy)
------------------------------------------------------------------------
Two active, not-already-flagged jobs from *different* sources are a
duplicate pair if and only if:

    1. ``normalize_for_matching(job_title)`` is identical, AND
    2. ``normalize_for_matching(company_name)`` is identical, AND
    3. their ``posting_date`` values are within
       ``DedupSettings.posting_date_window_days`` of each other.

No fuzzy/similarity-threshold library (e.g. ``rapidfuzz``) is used —
none is currently a project dependency, and introducing one was
explicitly deferred until fuzzy matching is actually wanted. The date
window (rather than requiring an exact date match) exists because
different job boards are not guaranteed to record "posting date" with
identical granularity or timezone handling for what is otherwise the
same listing — see ``DedupSettings.posting_date_window_days``'s
docstring.

``content_hash`` (already computed identically for every source by
``db.job_repository.compute_job_content_hash``) is recorded alongside
each match as a secondary confidence signal — a hash collision across
two different ``source_id``s is strong corroborating evidence that
title+company+description+location+salary line up exactly — but it is
NOT required for a match, since minor per-source text differences
(whitespace, leftover HTML fragments, syndication rewording) will
legitimately break hash equality even for genuine duplicates.

Canonical selection (confirmed design decision)
--------------------------------------------------
Within a matched group, the job belonging to the source with the
highest ``ref.sources.trust_score`` becomes canonical (keeps
``is_duplicate_of IS NULL``); every other job in the group gets
``is_duplicate_of`` set to the canonical job's ``job_id``. Ties broken
by earliest ``posting_date``. If ``trust_score`` is NULL for a source
(schema allows it), it sorts as if it were the lowest possible score —
a source explicitly not yet trust-scored should not out-rank one that
has been.

Scale note: this module fetches all currently-active, not-yet-flagged
jobs into memory and groups them in Python rather than attempting the
matching as a single SQL self-join. That is appropriate at this
project's current volume (three low-volume sources, Phase 4) and
intentionally not optimized for the 100M-row target scale described in
the design doc — revisit with a SQL-side or windowed approach if/when
job volume makes an in-memory pass impractical. Flagged here rather than
silently accepted as permanent.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.normalization.config import DedupSettings, get_dedup_settings

#: Matches any run of whitespace.
_WHITESPACE_RUN = re.compile(r"\s+")

#: Matches characters this module treats as noise for matching purposes
#: only (never for display/storage) — punctuation that commonly differs
#: between two otherwise-identical strings scraped from different sites
#: (e.g. "Sr. Data Scientist" vs "Sr Data Scientist", "Acme, Inc."
#: vs "Acme Inc"). Deliberately narrow: this is normalization for exact
#: comparison, not fuzzy matching, so it only strips characters that
#: would otherwise cause an obviously-identical string to fail equality.
_MATCH_NOISE_CHARS = re.compile(r"[.,\-_/\\'\"()&]")


def normalize_for_matching(text_value: str) -> str:
    """Normalize a title or company string for exact-match comparison.

    Lowercases, strips a narrow set of punctuation noise characters,
    and collapses/trims whitespace. This is intentionally simpler than
    ``cleaning.text_utils.clean_plain_text`` (which handles mojibake and
    HTML entities — concerns for *display* text, already applied
    upstream by each source's cleaner before the string ever reaches
    ``core.jobs``) — this function only needs to make two
    already-cleaned strings compare equal despite superficial
    punctuation/casing differences between sources.

    Args:
        text_value: Already-cleaned display text (e.g.
            ``core.jobs.job_title`` or ``core.companies.company_name``).

    Returns:
        The normalized string, suitable for equality comparison only —
        never for display.
    """
    lowered = text_value.lower()
    no_noise = _MATCH_NOISE_CHARS.sub("", lowered)
    return _WHITESPACE_RUN.sub(" ", no_noise).strip()


@dataclass(frozen=True)
class JobDedupRecord:
    """One active, not-yet-flagged job, as fetched for matching.

    Deliberately not a pydantic ``BaseModel`` like ``CleanedJob`` — this
    is an internal working shape for this module only, never crosses a
    module boundary as a public contract the way ``CleanedJob`` does.
    """

    job_id: int
    posting_date: date
    source_id: int
    source_code: str
    trust_score: float | None
    job_title: str
    company_name: str
    content_hash: str


@dataclass(frozen=True)
class DuplicateMatch:
    """One resolved duplicate pair: a non-canonical job pointing at its canonical counterpart."""

    duplicate_job_id: int
    duplicate_posting_date: date
    duplicate_source_code: str
    canonical_job_id: int
    canonical_posting_date: date
    canonical_source_code: str
    normalized_title: str
    normalized_company: str
    content_hash_matched: bool


def fetch_dedup_candidates(session: Session) -> list[JobDedupRecord]:
    """Fetches every active, not-yet-flagged job as a matching candidate.

    Scope, matching the module docstring: only ``job_status = 'active'``
    (no point flagging a closed/expired posting as a duplicate) and only
    ``is_duplicate_of IS NULL`` (a job already flagged in a prior batch
    run is left alone — this function is safe to call repeatedly across
    runs without re-processing already-resolved rows).
    """
    rows = session.execute(
        text(
            "SELECT "
            "  j.job_id, j.posting_date, j.source_id, s.source_code, s.trust_score, "
            "  j.job_title, c.company_name, j.content_hash "
            "FROM core.jobs j "
            "JOIN ref.sources s ON s.source_id = j.source_id "
            "JOIN core.companies c ON c.company_id = j.company_id "
            "WHERE j.job_status = 'active' AND j.is_duplicate_of IS NULL"
        )
    ).all()

    return [
        JobDedupRecord(
            job_id=row.job_id,
            posting_date=row.posting_date,
            source_id=row.source_id,
            source_code=row.source_code,
            trust_score=float(row.trust_score) if row.trust_score is not None else None,
            job_title=row.job_title,
            company_name=row.company_name,
            content_hash=row.content_hash,
        )
        for row in rows
    ]


def _canonical_sort_key(record: JobDedupRecord) -> tuple[float, date]:
    """Sort key selecting the canonical record: highest trust_score first
    (NULL treated as lowest), earliest posting_date as tiebreak.
    """
    trust = record.trust_score if record.trust_score is not None else -1.0
    return (-trust, record.posting_date)


def find_duplicate_matches(
    records: list[JobDedupRecord],
    settings: DedupSettings | None = None,
) -> list[DuplicateMatch]:
    """Groups candidates by normalized (title, company) and resolves
    canonical vs. duplicate within each group, per the module's
    confirmed matching/canonical-selection rules.

    A job only ever gets flagged as a duplicate of ONE canonical job, even
    if it falls within the date window of multiple same-key candidates —
    it's matched against the single group-wide canonical (highest
    trust_score, tie-break earliest posting_date), not against every
    individual candidate it happens to be close to.
    """
    settings = settings or get_dedup_settings()
    window = settings.posting_date_window_days

    groups: dict[tuple[str, str], list[JobDedupRecord]] = defaultdict(list)
    for record in records:
        key = (
            normalize_for_matching(record.job_title),
            normalize_for_matching(record.company_name),
        )
        groups[key].append(record)

    matches: list[DuplicateMatch] = []

    for (norm_title, norm_company), group in groups.items():
        if len(group) < 2:
            continue

        # A "match" additionally requires >= 2 distinct sources in the
        # group -- multiple postings from the SAME source with an
        # identical normalized title+company are not this module's
        # concern (same-source dedup is Step 10's content_hash-based
        # (source_id, source_job_id) natural key, already handled).
        distinct_sources = {r.source_id for r in group}
        if len(distinct_sources) < 2:
            continue

        ordered = sorted(group, key=_canonical_sort_key)
        canonical = ordered[0]

        for candidate in ordered[1:]:
            if candidate.source_id == canonical.source_id:
                # Same source as the chosen canonical -- not this
                # module's concern (see above); skip rather than flag.
                continue

            date_gap = abs((candidate.posting_date - canonical.posting_date).days)
            if date_gap > window:
                continue

            matches.append(
                DuplicateMatch(
                    duplicate_job_id=candidate.job_id,
                    duplicate_posting_date=candidate.posting_date,
                    duplicate_source_code=candidate.source_code,
                    canonical_job_id=canonical.job_id,
                    canonical_posting_date=canonical.posting_date,
                    canonical_source_code=canonical.source_code,
                    normalized_title=norm_title,
                    normalized_company=norm_company,
                    content_hash_matched=candidate.content_hash == canonical.content_hash,
                )
            )

    return matches


def apply_duplicate_matches(
    session: Session,
    matches: list[DuplicateMatch],
    actor_label: str = "dedup_batch",
) -> int:
    """Persists resolved matches: sets ``core.jobs.is_duplicate_of`` on
    every non-canonical row and appends one ``audit.change_log`` entry
    per match.

    Does not commit — that's the caller's/unit-of-work's responsibility,
    matching every other repository-style function in this project (see
    ``db.job_repository``'s module-level convention).

    Audit trail choice: reuses ``audit.change_log`` rather than a new
    ``ops.*`` table. That table already exists, is already shaped for
    exactly this ("general-purpose audit trail... reference-data edits
    made by human curators/admins... distinct from job-level history" —
    design doc Section 5.15), and a dedup assignment is conceptually a
    curatorial edit to ``core.jobs.is_duplicate_of``, not a scraper
    ingestion event. ``actor_user_id`` is left NULL (no ``auth.users``
    row represents "the batch job itself" today) — ``old_data`` records
    the actor label instead, so it's still traceable to "this ran as the
    Step 19 dedup batch" without inventing a synthetic user.

    Returns:
        Number of ``core.jobs`` rows updated.
    """
    updated = 0

    for match in matches:
        # session.execute() is typed as returning the generic
        # sqlalchemy.engine.Result[Any], which has no `.rowcount`
        # attribute in its stub -- only its CursorResult subclass does,
        # which is what a raw UPDATE via text() actually returns at
        # runtime. Mirrors the documented, understood deviation already
        # in db.job_repository.JobRepository.model (see that module's
        # comment) rather than reaching for an unnecessary runtime cast.
        result = session.execute(
            text(
                "UPDATE core.jobs SET is_duplicate_of = :canonical_job_id, updated_at = now() "
                "WHERE job_id = :duplicate_job_id AND is_duplicate_of IS NULL"
            ),
            {
                "canonical_job_id": match.canonical_job_id,
                "duplicate_job_id": match.duplicate_job_id,
            },
        )

        if result.rowcount == 0:  # type: ignore[attr-defined]
            # Already flagged by a concurrent/prior run since
            # fetch_dedup_candidates ran -- skip rather than double-log.
            continue

        updated += result.rowcount  # type: ignore[attr-defined]

        session.execute(
            text(
                "INSERT INTO audit.change_log "
                "(table_name, record_id, operation, old_data, new_data, actor_user_id) "
                "VALUES (:table_name, :record_id, 'update', :old_data, :new_data, NULL)"
            ),
            {
                "table_name": "core.jobs",
                "record_id": match.duplicate_job_id,
                "old_data": _to_jsonb_param({"is_duplicate_of": None, "actor": actor_label}),
                "new_data": _to_jsonb_param(
                    {
                        "is_duplicate_of": match.canonical_job_id,
                        "canonical_source": match.canonical_source_code,
                        "duplicate_source": match.duplicate_source_code,
                        "normalized_title": match.normalized_title,
                        "normalized_company": match.normalized_company,
                        "content_hash_matched": match.content_hash_matched,
                    }
                ),
            },
        )

    logger.info(
        "Cross-source dedup batch: {} of {} resolved matches applied "
        "(remainder already flagged by a concurrent/prior run).",
        updated,
        len(matches),
    )
    return updated


def _to_jsonb_param(payload: dict[str, Any]) -> str:
    """Serializes a dict to a JSON string for a ``JSONB`` bind parameter.

    ``audit.change_log.old_data``/``new_data`` are ``JSONB`` columns;
    psycopg3 (this project's driver -- see ``db/config.py``) accepts a
    JSON-formatted string for a ``JSONB`` parameter via a plain
    ``text()`` insert without needing an explicit ``::jsonb`` cast,
    since PostgreSQL coerces a text literal assigned to a jsonb column
    automatically. Kept as an explicit helper (rather than inlining
    ``json.dumps`` at each call site) so both call sites above stay
    consistent if that ever needs to change (e.g. to add a cast).
    """
    import json

    return json.dumps(payload, default=str)


def run_dedup_batch(session: Session, settings: DedupSettings | None = None) -> dict[str, int]:
    """End-to-end batch run: fetch candidates, find matches, persist them.

    This is the single entry point ``scripts/run_dedup_batch.py`` calls.
    Does not commit (caller's unit of work, per this project's
    established `get_session()` convention).

    Returns:
        Dict with keys ``candidates_scanned``, ``matches_found``,
        ``matches_applied``.
    """
    settings = settings or get_dedup_settings()

    candidates = fetch_dedup_candidates(session)
    matches = find_duplicate_matches(candidates, settings=settings)
    applied = apply_duplicate_matches(session, matches)

    return {
        "candidates_scanned": len(candidates),
        "matches_found": len(matches),
        "matches_applied": applied,
    }

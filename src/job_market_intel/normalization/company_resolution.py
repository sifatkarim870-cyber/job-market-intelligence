"""Company alias candidate generation (Step 25).

Where this fits: the design doc's own words on ``core.companies`` --
"Same employer appears under slightly different names across sources
... resolution must happen at the data layer, not per-query" -- and on
``core.company_aliases`` -- "Maps raw name variants ... to a resolved
company_id ... appended as scrapers encounter them." Confirmed against
the real codebase before writing a line of this: ``core.company_aliases``
existed in the schema but was written to and read from nowhere. This
module is the first thing that writes to it.

What this deliberately is NOT (confirmed design decisions, not
assumptions):

    - NOT a change to ``db.job_repository.get_or_create_company``. That
      function stays exact-match-only, unchanged, at the hot write path.
      This module never runs inline during ingestion -- it is a separate
      batch job, scanning already-persisted ``core.companies`` rows,
      matching the same "batch job after ingestion" pattern already
      established by ``normalization/dedup.py`` / Step 19.
    - NOT auto-merge. This is a firm, explicitly non-default decision:
      no code path in this module ever changes ``core.jobs.company_id``
      or deletes/merges a ``core.companies`` row. The only writes are
      candidate rows into ``core.company_aliases`` (with a computed
      ``match_confidence``) and, via the separate reviewer script
      (``scripts/review_company_aliases.py``), a human-gated flip of
      ``core.companies.is_verified``. A false-positive merge would
      silently corrupt every downstream company-level analytic with no
      obvious signal that anything went wrong -- that risk is judged
      worse than leaving genuine duplicates unmerged a while longer.
    - NOT domain-based matching. No source captures a company website/
      domain today (confirmed: none of RemoteOK/WWR/Remotive's cleaners
      populate ``core.companies.domain``) -- ``domain`` stays unused by
      this module until a source provides it.

Matching strategy
------------------
Candidate pairs are found via PostgreSQL's ``pg_trgm`` ``similarity()``
function over a *corporate-suffix-stripped* form of
``core.companies.normalized_name`` (the trigram GIN index
``idx_companies_normalized_name_trgm`` already exists in the schema,
unused until now). This is deliberately *fuzzy*, unlike
``normalization.dedup``'s conservative exact-normalized matching --
company name variants ("Dexterra" vs "Dexterra Group") are a genuinely
different problem than cross-source duplicate postings, and don't share
a common normalized form the way ``normalize_for_matching`` produces for
near-identical job titles. No new dependency was introduced for this:
``pg_trgm`` is already an enabled extension (see schema Section 1), so
the similarity computation happens in SQL, not in a Python fuzzy-match
library.

Suffix stripping (added after real-data validation, not part of the
initial design): a first real dry run against the live 212-company
dataset at ``similarity_threshold=0.5`` surfaced one genuine match
("Dexterra" / "Dexterra Group", 0.60) and one false positive ("Zegogo
Corporation" / "YT Corporation", 0.55) -- two otherwise-unrelated
companies whose only real overlap is the generic word "Corporation".
Because the true and false positives sat only 0.05 apart, no similarity
threshold alone could separate them. ``strip_corporate_suffixes`` removes
one or more trailing generic corporate-suffix words (Inc, LLC, Ltd,
Corp/Corporation, Group, Holdings, Co/Company, PLC, GmbH, ...) before
similarity is computed, so "Zegogo Corporation" vs "YT Corporation"
becomes "zegogo" vs "yt" (correctly falls apart) while "Dexterra Group"
vs "Dexterra" becomes "dexterra" vs "dexterra" (correctly strengthens
toward 1.0). The same compiled pattern backs both the pure-Python
``strip_corporate_suffixes`` (directly unit-testable, no DB needed) and
the SQL ``regexp_replace`` used in ``fetch_alias_candidate_pairs`` --
one definition, not two implementations to keep in sync.

Canonical selection (once a candidate pair is found)
-------------------------------------------------------
Within a pair, the company with more associated ``core.jobs`` rows
becomes canonical (the more "established" identity in the actual data);
ties broken by shorter ``normalized_name`` (fewer characters usually
means fewer corporate-suffix words, e.g. "Dexterra" over "Dexterra
Group"); remaining ties broken by lower ``company_id`` (earlier-created
row). The other company's ``company_name`` is recorded as the candidate
alias's ``raw_name`` under the canonical's ``company_id``. Canonical
selection deliberately still uses the *unstripped* ``normalized_name``
for its length tiebreak -- suffix stripping is a similarity-matching
concern only, not a canonical-selection one; a suffix word is still
meaningful, real information about which name is the fuller/more formal
one, so it isn't discarded once a pair has already been matched.

Rejection is sticky (added after real usage surfaced a real bug, not
part of the initial design): the first real review session hit this
directly -- a candidate was rejected via ``scripts/review_company_aliases.py``,
which deleted its ``core.company_aliases`` row, and the very next batch
run re-proposed the identical pair, because the "don't re-propose an
already-recorded candidate" exclusion only checked for a *currently
existing* alias row -- once rejection deleted it, nothing was left to
exclude it. ``reject_alias_candidates`` now also writes an
``audit.change_log`` row (``operation='delete'``) recording exactly what
was rejected, and ``fetch_alias_candidate_pairs`` excludes any pair with
a matching rejection logged there, not just a matching currently-active
alias row.

Scale note: like ``normalization/dedup.py``, this module's pair-fetch
query is an O(n^2) self-join over ``core.companies`` evaluated entirely
in SQL. At this project's current volume (low hundreds of companies)
that's trivial; it is NOT optimized for the 100M-job / millions-of-
companies target scale described in the design doc. Flagged here rather
than silently accepted as permanent -- revisit (e.g. blocking/windowing
by first-trigram or a nearest-neighbor index strategy) if/when company
volume makes an all-pairs scan impractical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.normalization.config import (
    CompanyResolutionSettings,
    get_company_resolution_settings,
)

#: Generic corporate-suffix words stripped from the *end* of a company
#: name before similarity is computed -- see "Suffix stripping" above.
#: Deliberately a narrow, common-sense list (not exhaustive of every
#: possible jurisdiction's legal-entity suffix); extend it if real
#: review data (via scripts/review_company_aliases.py) surfaces another
#: recurring false-positive pattern.
_CORPORATE_SUFFIX_WORDS = (
    "incorporated",
    "corporation",
    "corp",
    "llc",
    "ltd",
    "limited",
    "company",
    "group",
    "holdings",
    "enterprises",
    "industries",
    "plc",
    "gmbh",
    "llp",
    "lp",
    "inc",
    "co",
)

#: Matches one-or-more trailing " <suffix-word>" sequences at the end of
#: a string, e.g. both "group" and "holdings" in "Acme Holdings Group".
#: Compatible with both Python's `re` (used by strip_corporate_suffixes
#: below) and PostgreSQL's regexp_replace (used in
#: fetch_alias_candidate_pairs's SQL) -- both support the `(?:...)`
#: non-capturing group, `|` alternation, and `+` repetition used here.
_SUFFIX_STRIP_PATTERN = r"(?:\s+(?:" + "|".join(_CORPORATE_SUFFIX_WORDS) + r")\.?)+$"
_SUFFIX_STRIP_RE = re.compile(_SUFFIX_STRIP_PATTERN, re.IGNORECASE)


def strip_corporate_suffixes(normalized_name: str) -> str:
    """Strips trailing generic corporate-suffix words from an
    already-normalized (lowercased) company name, for similarity
    matching only -- never for display or storage.

    Falls back to the original ``normalized_name`` if stripping would
    leave nothing behind (e.g. a company literally named "Group Inc" in
    full -- pathological, but safer than comparing empty strings).

    Args:
        normalized_name: Already-lowercased ``core.companies.normalized_name``.

    Returns:
        The suffix-stripped name, or the original if stripping empties it.
    """
    stripped = _SUFFIX_STRIP_RE.sub("", normalized_name).strip()
    return stripped if stripped else normalized_name


@dataclass(frozen=True)
class CompanyRecord:
    """One ``core.companies`` row, as fetched for candidate matching."""

    company_id: int
    company_name: str
    normalized_name: str
    job_count: int


@dataclass(frozen=True)
class CompanyAliasCandidate:
    """One proposed alias: ``alias_company_name`` is a likely variant of
    ``canonical_company_name``, pending human review.
    """

    canonical_company_id: int
    canonical_company_name: str
    alias_company_id: int
    alias_company_name: str
    similarity_score: float


def _canonical_sort_key(record: CompanyRecord) -> tuple[int, int, int]:
    """Sort key selecting the canonical record within a pair: most
    ``core.jobs`` rows first, then shortest ``normalized_name``, then
    lowest ``company_id`` as a final, deterministic tiebreak.
    """
    return (-record.job_count, len(record.normalized_name), record.company_id)


def fetch_alias_candidate_pairs(
    session: Session,
    settings: CompanyResolutionSettings | None = None,
) -> list[tuple[CompanyRecord, CompanyRecord, float]]:
    """Fetches candidate company pairs whose *suffix-stripped*
    ``normalized_name`` trigram similarity meets
    ``settings.similarity_threshold`` -- see ``strip_corporate_suffixes``
    and the module docstring's "Suffix stripping" section for why this
    isn't computed on the raw ``normalized_name``.

    Excludes any pair for which a ``core.company_aliases`` row already
    links the two companies in either direction, OR for which a prior
    rejection was logged via ``reject_alias_candidates`` -- so this
    function -- and therefore the whole batch job -- is safe to call
    repeatedly across runs without re-proposing an already-recorded *or*
    already-rejected candidate.

    Each ``core.companies`` row's ``job_count`` (count of associated
    ``core.jobs`` rows) is fetched in the same query since
    ``_canonical_sort_key`` needs it, avoiding a second round trip.
    """
    settings = settings or get_company_resolution_settings()

    rows = session.execute(
        text(
            "WITH company_stats AS ( "
            "  SELECT c.company_id, c.company_name, c.normalized_name, "
            "         COALESCE(NULLIF(regexp_replace(c.normalized_name, "
            "                  :suffix_pattern, '', 'gi'), ''), "
            "                  c.normalized_name) AS stripped_name, "
            "         count(j.job_id) AS job_count "
            "  FROM core.companies c "
            "  LEFT JOIN core.jobs j ON j.company_id = c.company_id "
            "  GROUP BY c.company_id, c.company_name, c.normalized_name "
            ") "
            "SELECT "
            "  a.company_id AS company_id_a, a.company_name AS company_name_a, "
            "  a.normalized_name AS normalized_name_a, a.job_count AS job_count_a, "
            "  b.company_id AS company_id_b, b.company_name AS company_name_b, "
            "  b.normalized_name AS normalized_name_b, b.job_count AS job_count_b, "
            "  similarity(a.stripped_name, b.stripped_name) AS sim "
            "FROM company_stats a "
            "JOIN company_stats b ON a.company_id < b.company_id "
            "WHERE similarity(a.stripped_name, b.stripped_name) >= :threshold "
            "AND NOT EXISTS ( "
            "  SELECT 1 FROM core.company_aliases ca "
            "  WHERE (ca.company_id = a.company_id AND ca.raw_name = b.company_name) "
            "     OR (ca.company_id = b.company_id AND ca.raw_name = a.company_name) "
            ") "
            "AND NOT EXISTS ( "
            "  SELECT 1 FROM audit.change_log cl "
            "  WHERE cl.table_name = 'core.company_aliases' AND cl.operation = 'delete' "
            "  AND ( "
            "    (cl.record_id = a.company_id "
            "     AND cl.old_data->>'alias_raw_name' = b.company_name) "
            "    OR (cl.record_id = b.company_id "
            "        AND cl.old_data->>'alias_raw_name' = a.company_name) "
            "  ) "
            ") "
            "ORDER BY sim DESC"
        ),
        {"threshold": settings.similarity_threshold, "suffix_pattern": _SUFFIX_STRIP_PATTERN},
    ).all()

    pairs: list[tuple[CompanyRecord, CompanyRecord, float]] = []
    for row in rows:
        record_a = CompanyRecord(
            company_id=row.company_id_a,
            company_name=row.company_name_a,
            normalized_name=row.normalized_name_a,
            job_count=row.job_count_a,
        )
        record_b = CompanyRecord(
            company_id=row.company_id_b,
            company_name=row.company_name_b,
            normalized_name=row.normalized_name_b,
            job_count=row.job_count_b,
        )
        pairs.append((record_a, record_b, float(row.sim)))

    return pairs


def build_alias_candidates(
    pairs: list[tuple[CompanyRecord, CompanyRecord, float]],
) -> list[CompanyAliasCandidate]:
    """Resolves canonical-vs-alias direction for each fetched pair.

    Pure Python, no session -- mirrors ``dedup.find_duplicate_matches``'s
    separation of "matching logic" from "SQL fetch" so this is directly
    unit-testable against synthetic ``CompanyRecord`` pairs.
    """
    candidates: list[CompanyAliasCandidate] = []

    for record_a, record_b, similarity_score in pairs:
        canonical, alias = sorted((record_a, record_b), key=_canonical_sort_key)

        candidates.append(
            CompanyAliasCandidate(
                canonical_company_id=canonical.company_id,
                canonical_company_name=canonical.company_name,
                alias_company_id=alias.company_id,
                alias_company_name=alias.company_name,
                similarity_score=similarity_score,
            )
        )

    return candidates


def apply_alias_candidates(
    session: Session,
    candidates: list[CompanyAliasCandidate],
    actor_label: str = "company_resolution_batch",
) -> int:
    """Persists candidate aliases: inserts one ``core.company_aliases``
    row per candidate (``source_id`` left NULL -- this candidate wasn't
    produced by a scraper, it was derived by comparing two existing
    ``core.companies`` rows to each other) and one ``audit.change_log``
    entry per insert.

    Never touches ``core.jobs.company_id`` or
    ``core.companies.is_verified`` -- confirming the firm "no auto-merge"
    decision at the code level, not just in the docstring above.

    Does not commit -- caller's/unit-of-work's responsibility, matching
    every other function in this project that writes via a passed-in
    ``Session`` (see ``normalization.dedup.apply_duplicate_matches``).

    Returns:
        Number of ``core.company_aliases`` rows inserted.
    """
    inserted = 0

    for candidate in candidates:
        existing = session.execute(
            text(
                "SELECT alias_id FROM core.company_aliases "
                "WHERE company_id = :company_id AND raw_name = :raw_name "
                "AND source_id IS NULL"
            ),
            {
                "company_id": candidate.canonical_company_id,
                "raw_name": candidate.alias_company_name,
            },
        ).scalar()

        if existing is not None:
            # Already recorded by a concurrent/prior run -- skip rather
            # than insert a duplicate candidate row (the UNIQUE
            # (raw_name, source_id) constraint would not catch this
            # itself, since multiple NULL source_id rows don't collide).
            continue

        session.execute(
            text(
                "INSERT INTO core.company_aliases "
                "(company_id, raw_name, source_id, match_confidence) "
                "VALUES (:company_id, :raw_name, NULL, :match_confidence)"
            ),
            {
                "company_id": candidate.canonical_company_id,
                "raw_name": candidate.alias_company_name,
                "match_confidence": round(candidate.similarity_score, 2),
            },
        )
        inserted += 1

        session.execute(
            text(
                "INSERT INTO audit.change_log "
                "(table_name, record_id, operation, old_data, new_data, actor_user_id) "
                "VALUES (:table_name, :record_id, 'insert', NULL, :new_data, NULL)"
            ),
            {
                "table_name": "core.company_aliases",
                "record_id": candidate.canonical_company_id,
                "new_data": _to_jsonb_param(
                    {
                        "actor": actor_label,
                        "canonical_company_id": candidate.canonical_company_id,
                        "canonical_company_name": candidate.canonical_company_name,
                        "alias_company_id": candidate.alias_company_id,
                        "alias_raw_name": candidate.alias_company_name,
                        "similarity_score": candidate.similarity_score,
                    }
                ),
            },
        )

    logger.info(
        "Company resolution batch: {} of {} candidates inserted "
        "(remainder already recorded by a concurrent/prior run).",
        inserted,
        len(candidates),
    )
    return inserted


def reject_alias_candidates(
    session: Session,
    canonical_company_id: int,
    canonical_company_name: str,
    alias_raw_names: list[str],
    actor_label: str = "company_alias_review",
) -> int:
    """Rejects one or more pending alias candidates under a single
    canonical company: deletes their ``core.company_aliases`` rows AND
    logs the rejection to ``audit.change_log`` so
    ``fetch_alias_candidate_pairs`` won't re-propose the identical pair
    on a future batch run.

    This is what makes rejection *sticky* -- see the module docstring's
    "Rejection is sticky" section for the real bug this fixes (a
    rejected candidate reappearing on the very next batch run, because
    deleting its only record of having existed also deleted the only
    thing excluding it).

    ``scripts/review_company_aliases.py`` calls this rather than
    deleting ``core.company_aliases`` rows directly, so the CLI reviewer
    stays a thin wrapper around already-tested library logic (matching
    this project's established convention -- see ``apply_alias_candidates``
    and ``normalization.dedup.apply_duplicate_matches``).

    Does not commit -- caller's/unit-of-work's responsibility.

    Args:
        canonical_company_id: The ``company_id`` the candidate(s) were
            proposed as aliases *of*.
        canonical_company_name: For the ``audit.change_log`` record only.
        alias_raw_names: The ``raw_name`` value(s) being rejected.

    Returns:
        Number of ``core.company_aliases`` rows deleted.
    """
    if not alias_raw_names:
        return 0

    result = session.execute(
        text(
            "DELETE FROM core.company_aliases "
            "WHERE company_id = :company_id AND raw_name = ANY(:raw_names) "
            "AND source_id IS NULL"
        ),
        {"company_id": canonical_company_id, "raw_names": alias_raw_names},
    )
    # session.execute() is typed as returning the generic
    # sqlalchemy.engine.Result[Any], which has no `.rowcount` attribute
    # in its stub -- only its CursorResult subclass does, which is what
    # a raw DELETE via text() actually returns at runtime. Same
    # documented deviation as normalization.dedup.apply_duplicate_matches.
    deleted = result.rowcount  # type: ignore[attr-defined]

    for raw_name in alias_raw_names:
        session.execute(
            text(
                "INSERT INTO audit.change_log "
                "(table_name, record_id, operation, old_data, new_data, actor_user_id) "
                "VALUES (:table_name, :record_id, 'delete', :old_data, NULL, NULL)"
            ),
            {
                "table_name": "core.company_aliases",
                "record_id": canonical_company_id,
                "old_data": _to_jsonb_param(
                    {
                        "actor": actor_label,
                        "canonical_company_id": canonical_company_id,
                        "canonical_company_name": canonical_company_name,
                        "alias_raw_name": raw_name,
                    }
                ),
            },
        )

    logger.info(
        "Company resolution batch: {} candidate(s) rejected under company_id={} "
        "(logged to audit.change_log, will not be re-proposed).",
        deleted,
        canonical_company_id,
    )
    return deleted


def _to_jsonb_param(payload: dict[str, Any]) -> str:
    """Serializes a dict to a JSON string for a ``JSONB`` bind parameter.

    Identical approach to, and for the same reason as,
    ``normalization.dedup._to_jsonb_param`` -- kept as a separate copy
    rather than importing across modules, matching that this project's
    established convention keeps each batch-job module self-contained
    (``dedup.py`` doesn't import anything from ``company_resolution.py``
    either, and neither should depend on internal helpers of the other
    surviving a future refactor of either one).
    """
    import json

    return json.dumps(payload, default=str)


def run_company_resolution_batch(
    session: Session,
    settings: CompanyResolutionSettings | None = None,
) -> dict[str, int]:
    """End-to-end batch run: fetch pairs, resolve canonical/alias
    direction, persist candidates.

    This is the single entry point ``scripts/run_company_resolution_batch.py``
    calls. Does not commit (caller's unit of work, per this project's
    established ``get_session()`` convention).

    Returns:
        Dict with keys ``pairs_scanned``, ``candidates_found``,
        ``candidates_applied``.
    """
    settings = settings or get_company_resolution_settings()

    pairs = fetch_alias_candidate_pairs(session, settings=settings)
    candidates = build_alias_candidates(pairs)
    applied = apply_alias_candidates(session, candidates)

    return {
        "pairs_scanned": len(pairs),
        "candidates_found": len(candidates),
        "candidates_applied": applied,
    }

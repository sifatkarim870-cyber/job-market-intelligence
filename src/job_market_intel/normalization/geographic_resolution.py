"""Geographic location resolution (Step 28).

Where this fits: the design doc's ``ref.locations`` -- "the table jobs
actually reference; represents a *resolved posting location*, which may
be a real city, 'Remote — Country X,' 'Remote — Global,' or 'Hybrid —
City X.'" Confirmed against the real codebase before writing a line of
this: ``ref.locations`` existed in the schema from day one but nothing
ever wrote to it, and ``core.jobs.location_id`` /
``core.jobs.remote_work_type_id`` have been NULL on every job ever
ingested. This module is the first thing that writes to it.

Why this runs INLINE from ``db.job_repository.save_cleaned_job``, not as
a deferred batch job (unlike Step 25's ``company_resolution.py`` / Step
26's ``skill_extraction.py``) -- a real, confirmed-not-assumed
architectural constraint, not a style preference chosen up front:
``CleanedJob.location_cleaned`` is NEVER itself persisted anywhere in the
schema. Confirmed by reading ``db.job_repository.py`` directly --
``location_cleaned`` is used only as one input to
``compute_job_content_hash`` and is then discarded; no column on
``core.jobs`` or anywhere else stores the raw string. A batch job
scanning already-persisted ``core.jobs`` rows for ones needing location
resolution would therefore have nothing left to resolve them WITH -- the
one point in the entire pipeline where the raw string still exists is
inside ``save_cleaned_job`` itself, while the ``CleanedJob`` is still in
memory. (The original Step 28 proposal assumed a batch-job architecture
mirroring company resolution before this was checked against the real
code -- flagged and corrected here rather than silently building the
wrong thing.)

What this deliberately is NOT:
    - NOT fuzzy matching. Per the confirmed design decision, matching is
      exact (case-insensitive) against ``ref.cities``/``ref.regions``/
      ``ref.countries`` plus a small curated country-name/abbreviation
      map (``_COUNTRY_NAME_ALIASES``) -- country/region names have far
      less spelling variance than company names, and an explicit alias
      map is auditable in a way a similarity threshold isn't. Revisit
      with ``pg_trgm`` (as ``company_resolution.py`` does) only if real
      ``match_method='fallback_unmatched'`` volume in
      ``core.location_aliases`` shows exact matching is missing a lot.
    - NOT auto-widening ``ref.cities``/``ref.regions``/``ref.countries``.
      This module never inserts a new reference-data row into those three
      tables -- only into ``ref.locations`` (the resolved-combo dimension
      table) and ``core.location_aliases`` (the cache/audit table). If the
      curated seed set doesn't cover a real string, it falls back to
      ``remote_global`` (see ``resolve_location_text``'s docstring) rather
      than fabricating a new city/country.

Matching strategy
------------------
A raw string is split on ``;`` into segments (only We Work Remotely's
cleaner currently produces multi-segment strings -- confirmed in
``cleaning/weworkremotely_cleaner.py``, which concatenates up to three raw
signals this way; RemoteOK and Remotive never contain ``;``, so the split
is a no-op single-element list for those sources). Each segment has a
leading remote/hybrid/on-site qualifier stripped (e.g. ``"Remote - US"`` ->
``"US"``), then is matched, in order, against a seeded city name, a seeded
region name, and finally a seeded country name/ISO code (via the alias
map). The MOST SPECIFIC match across all segments wins (city > region >
country > explicit global assertion > unmatched) -- confirmed design
decision for handling We Work Remotely's multi-signal strings without
silently discarding a real match that happens to be listed first but is
least specific (e.g. ``"Anywhere in the World; France; Berlin"`` resolves
to Berlin, a real city match, not "anywhere").

Known, accepted limitation of "most specific wins" as a tie-break: it
assumes later/more-specific segments REFINE earlier ones, which holds for
the common case (a country plus one of its own cities/states) but not for
a segment list describing unrelated ALTERNATIVES in different countries
(e.g. ``"Argentina; Texas"``, meaning "open to Argentina OR US/Texas
candidates," not "Texas within Argentina"). A ref.regions (state/province)
match currently outranks a ref.countries match regardless of which
country each belongs to, so a string like that resolves to the region
match (Texas) even though the two segments describe unrelated options,
not a refinement. Not fixed here -- doing so correctly would require
detecting whether a region and a country segment share the same country,
which isn't needed by any of the three live sources' actual fixture data
(see cleaning/weworkremotely_cleaner.py's tests) and would add real
complexity for a case not yet observed in practice. Revisit if real
``core.location_aliases`` data shows this cross-country-alternatives
pattern is common enough to matter.

Global vs. unmatched fallback -- kept distinguishable (confirmed design
decision): a segment that explicitly says "Worldwide"/"Anywhere"/etc. gets
``is_global_remote=True`` and ``match_method='global_assertion'``. A raw
string where NOTHING matched anything (no city/region/country, no global
keyword either) ALSO resolves to ``remote_global`` -- the curated
~90-city/55-country seed set cannot cover every free-text location a
global remote-jobs feed will produce, and leaving ``location_id`` NULL
forever would defeat the point of this step -- but with
``is_global_remote=False`` and ``match_method='fallback_unmatched'``, so a
query can distinguish "this job asserted it's open worldwide" from "we
simply couldn't parse this one" without any schema change.

Deduplication of resolved locations (confirmed Postgres behavior, not an
assumption -- see ``get_or_create_location``'s docstring): PostgreSQL
treats NULL as DISTINCT from NULL in a UNIQUE constraint by default, so
the schema's ``UNIQUE (city_id, region_id, country_id,
remote_work_type_id)`` on ``ref.locations`` does NOT, by itself, stop two
separate INSERTs of ``(NULL, NULL, NULL, remote_global)`` from both
succeeding -- and given the seed coverage gaps, most resolved locations
WILL have all three NULL. ``get_or_create_location`` therefore looks up
existing rows with ``IS NOT DISTINCT FROM`` rather than ``=``, so
``ref.locations`` correctly collapses onto one reusable "unresolved
global remote" dimension row instead of accumulating a duplicate per
distinct unmatched raw string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session


class _MatchLevel(Enum):
    """Specificity ordering used to pick the best match across a
    multi-segment raw string's segments -- higher value wins.
    """

    UNMATCHED = -1
    GLOBAL = 0
    COUNTRY = 1
    REGION = 2
    CITY = 3


@dataclass(frozen=True)
class _SegmentMatch:
    level: _MatchLevel
    city_id: int | None = None
    region_id: int | None = None
    country_id: int | None = None


@dataclass(frozen=True)
class ResolvedLocation:
    """The outcome of resolving one raw location string: what to write to
    (or look up in) ``ref.locations``, plus ``match_method`` for
    ``core.location_aliases``'s audit trail.
    """

    city_id: int | None
    region_id: int | None
    country_id: int | None
    remote_work_type_code: str
    is_global_remote: bool
    match_method: str


#: Common free-text variants mapped onto the exact ref.countries.country_name
#: value seeded by seed/countries.py -- confirmed against the real seed list
#: (53 rows across every populated continent) before writing this, not
#: guessed. Keys are lowercased; matched against an already-lowercased,
#: prefix-stripped segment. Deliberately a narrow, common-sense list (not
#: exhaustive of every possible colloquial country reference); extend it if
#: real core.location_aliases match_method='fallback_unmatched' volume
#: surfaces another recurring pattern.
_COUNTRY_NAME_ALIASES: dict[str, str] = {
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "us": "United States",
    "america": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "uae": "United Arab Emirates",
    "holland": "Netherlands",
    "czech republic": "Czechia",
    "korea": "South Korea",
    "south-korea": "South Korea",
}

#: Segments matching one of these (after prefix-stripping and lowering) are
#: treated as an explicit, unambiguous "no narrower claim than fully
#: remote" assertion -- NOT the same as the UNMATCHED fallback; see the
#: module docstring's "Global vs. unmatched fallback" section.
_GLOBAL_ASSERTION_PHRASES: frozenset[str] = frozenset(
    {
        "worldwide",
        "anywhere",
        "anywhere in the world",
        "global",
        "globally",
        "international",
        "world",
    }
)

#: Strips a leading remote/hybrid/on-site qualifier and its trailing
#: separator (space, hyphen, colon, comma) from a segment before matching,
#: e.g. "Remote - US" -> "US", "Remote, Worldwide" -> "Worldwide". Matches
#: phrasing observed in the RemoteOK/Remotive/WWR cleaner test fixtures
#: during this step's investigation -- not exhaustive of every possible
#: phrasing a future source might use.
_REMOTE_PREFIX_RE = re.compile(r"^(?:remote|hybrid|on[\s-]?site)\b[\s\-,:]*", re.IGNORECASE)


def _normalize_segment(segment: str) -> str:
    """Lowercases, strips a leading remote/hybrid/on-site qualifier, and
    collapses whitespace. Pure text transform, no DB access -- directly
    unit-testable without a session.
    """
    cleaned = _REMOTE_PREFIX_RE.sub("", segment.strip())
    return " ".join(cleaned.split()).lower()


def split_location_segments(raw_text: str) -> list[str]:
    """Splits a raw ``location_cleaned`` string on ``;`` into candidate
    segments, stripping whitespace and dropping empties.

    See the module docstring's "Matching strategy" section for why only
    We Work Remotely currently produces multi-segment strings.
    """
    return [seg.strip() for seg in raw_text.split(";") if seg.strip()]


def _match_city(
    session: Session, normalized_segment: str
) -> tuple[int, int | None, int | None] | None:
    """Exact, case-insensitive match against ``ref.cities.city_name``.

    Returns ``(city_id, region_id, country_id)`` for a single unambiguous
    match, or ``None`` if there's no match OR more than one seeded city
    shares this name -- ambiguity is treated conservatively as no match
    rather than guessing (falls through to region/country/global
    matching on the same segment).
    """
    rows = session.execute(
        text(
            "SELECT city_id, region_id, country_id FROM ref.cities WHERE lower(city_name) = :name"
        ),
        {"name": normalized_segment},
    ).all()
    if len(rows) == 1:
        return rows[0].city_id, rows[0].region_id, rows[0].country_id
    return None


def _match_region(session: Session, normalized_segment: str) -> tuple[int, int | None] | None:
    """Exact, case-insensitive match against ``ref.regions.region_name``.
    Same ambiguity handling as ``_match_city``.
    """
    rows = session.execute(
        text("SELECT region_id, country_id FROM ref.regions WHERE lower(region_name) = :name"),
        {"name": normalized_segment},
    ).all()
    if len(rows) == 1:
        return rows[0].region_id, rows[0].country_id
    return None


def _match_country(session: Session, normalized_segment: str) -> int | None:
    """Matches a segment against ``ref.countries``, in order: the curated
    alias map (``_COUNTRY_NAME_ALIASES``), then an exact case-insensitive
    match against ``country_name``, ``iso_code_2``, or ``iso_code_3``.
    """
    aliased_name = _COUNTRY_NAME_ALIASES.get(normalized_segment)
    row = session.execute(
        text(
            "SELECT country_id FROM ref.countries WHERE "
            "lower(country_name) = :name OR lower(iso_code_2) = :code OR lower(iso_code_3) = :code"
        ),
        {"name": (aliased_name or normalized_segment).lower(), "code": normalized_segment},
    ).scalar()
    return int(row) if row is not None else None


def _match_segment(session: Session, segment: str) -> _SegmentMatch:
    """Resolves a single segment (one piece of a ``;``-split raw string)
    to its most specific match: city, then region, then country, then an
    explicit global assertion, then unmatched.
    """
    normalized = _normalize_segment(segment)
    if not normalized or normalized in _GLOBAL_ASSERTION_PHRASES:
        return _SegmentMatch(level=_MatchLevel.GLOBAL)

    city_match = _match_city(session, normalized)
    if city_match is not None:
        city_id, region_id, country_id = city_match
        return _SegmentMatch(
            level=_MatchLevel.CITY, city_id=city_id, region_id=region_id, country_id=country_id
        )

    region_match = _match_region(session, normalized)
    if region_match is not None:
        region_id, country_id = region_match
        return _SegmentMatch(level=_MatchLevel.REGION, region_id=region_id, country_id=country_id)

    country_id = _match_country(session, normalized)
    if country_id is not None:
        return _SegmentMatch(level=_MatchLevel.COUNTRY, country_id=country_id)

    return _SegmentMatch(level=_MatchLevel.UNMATCHED)


def resolve_location_text(session: Session, raw_text: str) -> ResolvedLocation:
    """Resolves a raw ``CleanedJob.location_cleaned`` string to a
    city/region/country + remote_work_type combination.

    See the module docstring's "Matching strategy" and "Global vs.
    unmatched fallback" sections for the full rationale. Pure resolution
    logic against already-seeded reference data -- does not write
    anything; pair with ``get_or_create_location`` to persist the result.
    """
    segments = split_location_segments(raw_text) or [raw_text]

    matches = [_match_segment(session, seg) for seg in segments]
    best_match = max(matches, key=lambda m: m.level.value)

    if best_match.level == _MatchLevel.CITY:
        return ResolvedLocation(
            city_id=best_match.city_id,
            region_id=best_match.region_id,
            country_id=best_match.country_id,
            remote_work_type_code="remote_city",
            is_global_remote=False,
            match_method="city_exact",
        )
    if best_match.level == _MatchLevel.REGION:
        # NOT remote_work_type_code="remote_region" -- confirmed against
        # the real seed data (seed/remote_work_types.py) before writing
        # this: "remote_region" means a MULTI-COUNTRY bloc (its own
        # description: "Remote within a multi-country region (e.g. EU,
        # LATAM, APAC)"), which is a completely different concept from a
        # ref.regions row (a state/province WITHIN one country, e.g.
        # "Texas", "Ontario"). A state/province match is still
        # fundamentally a single-country restriction -- just a narrower
        # one than the whole country -- so it buckets under
        # "remote_country" here, the same as a country-only match. The
        # extra precision isn't lost: region_id/country_id are still set
        # on the ref.locations row itself, and match_method='region_exact'
        # still records that a region (not just a bare country) was
        # actually matched, for auditability.
        return ResolvedLocation(
            city_id=None,
            region_id=best_match.region_id,
            country_id=best_match.country_id,
            remote_work_type_code="remote_country",
            is_global_remote=False,
            match_method="region_exact",
        )
    if best_match.level == _MatchLevel.COUNTRY:
        return ResolvedLocation(
            city_id=None,
            region_id=None,
            country_id=best_match.country_id,
            remote_work_type_code="remote_country",
            is_global_remote=False,
            match_method="country_exact",
        )
    if best_match.level == _MatchLevel.GLOBAL:
        return ResolvedLocation(
            city_id=None,
            region_id=None,
            country_id=None,
            remote_work_type_code="remote_global",
            is_global_remote=True,
            match_method="global_assertion",
        )
    return ResolvedLocation(
        city_id=None,
        region_id=None,
        country_id=None,
        remote_work_type_code="remote_global",
        is_global_remote=False,
        match_method="fallback_unmatched",
    )


def _get_remote_work_type_id(session: Session, code: str) -> int:
    row = session.execute(
        text("SELECT remote_work_type_id FROM ref.remote_work_types WHERE code = :code"),
        {"code": code},
    ).scalar()
    if row is None:
        raise RuntimeError(
            f"ref.remote_work_types has no row with code={code!r} -- database not seeded "
            "as expected (see seed/remote_work_types.py)."
        )
    return int(row)


def get_or_create_location(
    session: Session,
    city_id: int | None,
    region_id: int | None,
    country_id: int | None,
    remote_work_type_id: int,
    raw_location_text: str,
    is_global_remote: bool,
) -> int:
    """Get-or-create a ``ref.locations`` row for this exact
    ``(city_id, region_id, country_id, remote_work_type_id)`` combination.

    IMPORTANT (confirmed Postgres behavior -- see module docstring's
    "Deduplication of resolved locations" section): looks up existing rows
    with ``IS NOT DISTINCT FROM`` rather than ``=`` specifically because
    the schema's UNIQUE constraint does not itself prevent duplicate rows
    when city_id/region_id/country_id are all NULL, which is the common
    case given current seed coverage. Skipping this and using plain ``=``
    would silently accumulate one duplicate ``ref.locations`` row per
    distinct unmatched raw string instead of collapsing them.

    Not atomic against concurrent inserts of a brand-new combination
    (matches this project's existing ``get_or_create_company`` -- see that
    function -- current single-scraper-at-a-time execution makes this an
    accepted, documented, non-blocking risk rather than an oversight).
    """
    existing = session.execute(
        text(
            "SELECT location_id FROM ref.locations WHERE "
            "city_id IS NOT DISTINCT FROM :city_id AND "
            "region_id IS NOT DISTINCT FROM :region_id AND "
            "country_id IS NOT DISTINCT FROM :country_id AND "
            "remote_work_type_id = :remote_work_type_id"
        ),
        {
            "city_id": city_id,
            "region_id": region_id,
            "country_id": country_id,
            "remote_work_type_id": remote_work_type_id,
        },
    ).scalar()
    if existing is not None:
        return int(existing)

    new_id = session.execute(
        text(
            "INSERT INTO ref.locations "
            "(city_id, region_id, country_id, remote_work_type_id, "
            "raw_location_text, is_global_remote) "
            "VALUES (:city_id, :region_id, :country_id, :remote_work_type_id, "
            ":raw_location_text, :is_global_remote) "
            "RETURNING location_id"
        ),
        {
            "city_id": city_id,
            "region_id": region_id,
            "country_id": country_id,
            "remote_work_type_id": remote_work_type_id,
            "raw_location_text": raw_location_text,
            "is_global_remote": is_global_remote,
        },
    ).scalar()
    if new_id is None:
        raise RuntimeError("Failed to insert ref.locations row.")
    return int(new_id)


def resolve_and_cache_location(
    session: Session,
    raw_location_text: str | None,
    source_id: int | None,
) -> int | None:
    """The single entry point ``db.job_repository.save_cleaned_job`` calls.

    Returns a ``core.jobs.location_id``, or ``None`` if
    ``raw_location_text`` is missing/blank -- no signal to resolve, and
    fabricating a "global remote" guess for a job that simply didn't
    report a location at all would be a different, unwarranted claim from
    the ``fallback_unmatched`` case (where a location WAS reported, just
    not one this module could parse).

    Checks ``core.location_aliases`` first (keyed on
    ``(raw_location_text, source_id)`` -- the same raw string can carry
    different implied meaning across sources, so the cache is per-source,
    not global) and only runs the full segment-match logic on a cache
    miss, then records the result back to ``core.location_aliases`` for
    next time. See the module docstring's opening section for why this
    runs inline here rather than as a deferred batch job.
    """
    if raw_location_text is None:
        return None
    cleaned = raw_location_text.strip()
    if not cleaned:
        return None

    cached = session.execute(
        text(
            "SELECT location_id FROM core.location_aliases "
            "WHERE raw_location_text = :raw_text AND source_id IS NOT DISTINCT FROM :source_id"
        ),
        {"raw_text": cleaned, "source_id": source_id},
    ).scalar()
    if cached is not None:
        return int(cached)

    resolved = resolve_location_text(session, cleaned)
    remote_work_type_id = _get_remote_work_type_id(session, resolved.remote_work_type_code)
    location_id = get_or_create_location(
        session,
        city_id=resolved.city_id,
        region_id=resolved.region_id,
        country_id=resolved.country_id,
        remote_work_type_id=remote_work_type_id,
        raw_location_text=cleaned,
        is_global_remote=resolved.is_global_remote,
    )

    session.execute(
        text(
            "INSERT INTO core.location_aliases "
            "(raw_location_text, source_id, location_id, match_method) "
            "VALUES (:raw_text, :source_id, :location_id, :match_method)"
        ),
        {
            "raw_text": cleaned,
            "source_id": source_id,
            "location_id": location_id,
            "match_method": resolved.match_method,
        },
    )

    logger.debug(
        "Resolved location {!r} (source_id={}) -> location_id={} (method={}).",
        cleaned,
        source_id,
        location_id,
        resolved.match_method,
    )
    return location_id

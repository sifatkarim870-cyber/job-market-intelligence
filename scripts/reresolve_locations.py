"""Re-resolve job locations after the seed + resolver fix.

What was wrong
--------------
101,471 of 105,906 jobs pointed at ONE ``ref.locations`` row whose
``raw_location_text`` read ``Anywhere in the World; Nouvelle-Aquitaine`` --
an arbitrary string from whichever posting happened to create that row first.
``get_or_create_location`` collapses on
``(city_id, region_id, country_id, remote_work_type_id)``, so every job that
resolved to "no city, no country, remote_global" landed on the same row.

Of those, only ~3,056 came from remote-first boards and genuinely assert a
worldwide opening. The other ~96,330 came from single-country boards whose
city names this resolver could not read -- jobvision's 390 aliases are all
Persian ("تهران, تهران", "کرج, البرز") and Iran had no ``ref.countries`` row
at all, so the largest source in the corpus (58% of rows) was silently
reported as "open to the whole world".

What this does
--------------
Re-resolves each affected job from its ORIGINAL raw text in
``core.location_aliases`` and repoints ``core.jobs.location_id``. A job is
only moved when the new resolution is strictly more informative than the one
it had -- never away from a genuine city/country match, and never away from a
real ``global_assertion``.

Honesty constraint
------------------
The per-job raw text is NOT stored on ``core.jobs``; it survives only in
``core.location_aliases``, keyed by (raw text, source). So a job can only be
re-resolved if its source produced exactly ONE distinct alias that landed on
the collapsed row. Where a source produced many (jobvision: 390 cities), the
specific city is genuinely unrecoverable without re-fetching from the source,
and this script attributes the country -- the honest floor -- rather than
inventing a city. Those jobs are reported, not silently guessed.

Usage:
    python scripts/reresolve_locations.py --dry-run
    python scripts/reresolve_locations.py
"""

from __future__ import annotations

import argparse
import collections
import sys

from loguru import logger
from sqlalchemy import text

BATCH = 5000


def collapsed_row(session) -> int | None:
    """The catch-all row: remote_global with every geographic FK NULL."""
    return session.execute(
        text(
            "SELECT location_id FROM ref.locations "
            "WHERE city_id IS NULL AND region_id IS NULL AND country_id IS NULL "
            "AND remote_work_type_id = "
            "  (SELECT remote_work_type_id FROM ref.remote_work_types WHERE code='remote_global') "
            "ORDER BY location_id LIMIT 1"
        )
    ).scalar()


def _country_fallback_row(session, iso2: str) -> int | None:
    """The (no city, no region, this country, remote_country) location row."""
    from job_market_intel.normalization.geographic_resolution import (
        _get_remote_work_type_id,
        get_or_create_location,
    )

    country_id = session.execute(
        text("SELECT country_id FROM ref.countries WHERE iso_code_2 = :iso"),
        {"iso": iso2.upper()},
    ).scalar()
    if country_id is None:
        return None
    name = session.execute(
        text("SELECT country_name FROM ref.countries WHERE country_id = :c"),
        {"c": country_id},
    ).scalar()
    return get_or_create_location(
        session,
        city_id=None,
        region_id=None,
        country_id=int(country_id),
        remote_work_type_id=_get_remote_work_type_id(session, "remote_country"),
        raw_location_text=f"{name} (country inferred, city unresolved)",
        is_global_remote=False,
    )


def main(argv: list[str] | None = None) -> int:  # noqa: C901 - one linear audit pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from job_market_intel.normalization.geographic_resolution import (
        _get_remote_work_type_id,
        get_or_create_location,
        resolve_location_text,
        source_home_country,
    )

    engine = create_engine(
        "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
    )

    with Session(engine) as session:
        target = collapsed_row(session)
        if target is None:
            logger.info("no collapsed catch-all location row found; nothing to do")
            return 0

        affected = session.execute(
            text("SELECT count(*) FROM core.jobs WHERE location_id = :t"), {"t": target}
        ).scalar_one()
        logger.info("collapsed row location_id={} carries {:,} jobs", target, affected)
        if affected == 0:
            return 0

        # Which aliases produced this row, per source.
        aliases = session.execute(
            text(
                "SELECT a.source_id, s.source_code, a.raw_location_text, a.match_method "
                "FROM core.location_aliases a "
                "JOIN ref.sources s ON s.source_id = a.source_id "
                "WHERE a.location_id = :t"
            ),
            {"t": target},
        ).all()
        per_source: dict[int, list[str]] = collections.defaultdict(list)
        alias_texts: dict[int, list[str]] = collections.defaultdict(list)
        for source_id, source_code, raw, _method in aliases:
            per_source[source_id].append(source_code)
            alias_texts[source_id].append(raw)

        logger.info("{} distinct raw strings collapsed onto that row", len(aliases))
        for source_id, codes in sorted(per_source.items(), key=lambda kv: -len(kv[1])):
            logger.info(
                "  {:<14} {:>5} alias(es) collapsed here",
                codes[0],
                len(alias_texts[source_id]),
            )

        # Sources that never produced an alias row at all. Their jobs reached
        # this row without ever passing through resolve_and_cache_location --
        # the Neon->local merge mapped location_id by raw text and wrote no
        # audit trail -- so there is no per-alias text to check agreement
        # against. For a single-country board the home country is still the
        # honest floor, so these are attributed directly.
        plan: dict[int, int] = {}
        no_alias = session.execute(
            text(
                "SELECT j.source_id, s.source_code, count(*) "
                "FROM core.jobs j JOIN ref.sources s ON s.source_id = j.source_id "
                "WHERE j.location_id = :t AND NOT EXISTS ("
                "  SELECT 1 FROM core.location_aliases a "
                "  WHERE a.source_id = j.source_id AND a.location_id = :t) "
                "GROUP BY 1, 2 ORDER BY 3 DESC"
            ),
            {"t": target},
        ).all()
        for source_id, source_code, n in no_alias:
            iso = source_home_country(session, source_id)
            if iso is None:
                logger.info(
                    "  {:<14} SKIP - no aliases and no single home country ({} jobs)",
                    source_code,
                    f"{n:,}",
                )
                continue
            plan_extra = _country_fallback_row(session, iso)
            if plan_extra is None:
                logger.info(
                    "  {:<14} SKIP - home country {} has no ref.countries row ({} jobs)",
                    source_code,
                    iso,
                    f"{n:,}",
                )
                continue
            plan[source_id] = plan_extra
            logger.info(
                "  {:<14} no aliases; -> location_id={} country={} ({} jobs)",
                source_code,
                plan_extra,
                iso,
                f"{n:,}",
            )

        # For each source, decide the single best resolution to apply.
        # A source whose aliases disagree cannot be attributed to one country
        # honestly, so it is left alone and reported.
        plan_alias: dict[int, int] = {}
        plan_alias: dict[int, int] = {}
        for source_id, codes in per_source.items():
            source_code = codes[0]
            iso = source_home_country(session, source_id)
            if iso is None:
                logger.info(
                    "  {:<14} SKIP - multi-country/global board, no home country",
                    source_code,
                )
                continue
            # Every alias must land in the same place for one country-level
            # attribution to be truthful.
            results = {
                (
                    r.match_method,
                    r.country_id,
                    r.is_global_remote,
                )
                for r in (
                    resolve_location_text(session, raw, default_country_iso2=iso)
                    for raw in alias_texts[source_id]
                )
            }
            if len(results) != 1:
                logger.info(
                    "  {:<14} SKIP - {} distinct resolutions across {} aliases, "
                    "cannot attribute honestly",
                    source_code,
                    len(results),
                    len(alias_texts[source_id]),
                )
                continue
            r = resolve_location_text(session, alias_texts[source_id][0], default_country_iso2=iso)
            if r.match_method == "global_assertion":
                logger.info("  {:<14} SKIP - genuine worldwide assertion", source_code)
                continue
            if r.country_id is None:
                logger.info("  {:<14} SKIP - still resolves to no country", source_code)
                continue
            remote_id = _get_remote_work_type_id(session, r.remote_work_type_code)
            # Label by COUNTRY, not by source: jobvision and jobinja both
            # resolve to Iran and therefore share one row, and a source-named
            # label would arbitrarily name whichever ran first -- the exact
            # defect that put "Nouvelle-Aquitaine" on 101k rows.
            country_name = session.execute(
                text("SELECT country_name FROM ref.countries WHERE country_id = :c"),
                {"c": r.country_id},
            ).scalar()
            new_loc = get_or_create_location(
                session,
                city_id=r.city_id,
                region_id=r.region_id,
                country_id=r.country_id,
                remote_work_type_id=remote_id,
                raw_location_text=f"{country_name} (country inferred, city unresolved)",
                is_global_remote=r.is_global_remote,
            )
            plan_alias[source_id] = new_loc
            logger.info(
                "  {:<14} -> location_id={} country_id={} ({})",
                source_code,
                new_loc,
                r.country_id,
                iso,
            )

        plan_alias.update({k: v for k, v in plan_alias.items()})
        # An alias-derived attribution wins over the no-alias default: it was
        # checked for agreement across every raw string the source produced.
        plan = {**plan, **plan_alias}

        if not plan:
            logger.info("no source could be attributed safely; nothing changed")
            return 0

        total = 0
        for source_id in plan:
            n = session.execute(
                text("SELECT count(*) FROM core.jobs WHERE location_id = :t AND source_id = :s"),
                {"t": target, "s": source_id},
            ).scalar_one()
            total += n
            logger.info("  source_id={:<6} {:>8,} jobs would move", source_id, n)
        logger.info("total jobs to re-point: {:,}", total)

        if args.dry_run:
            logger.info("--dry-run: no changes written")
            return 0

        for source_id, new_loc in plan.items():
            session.execute(
                text(
                    "UPDATE core.jobs SET location_id = :new, updated_at = now() "
                    "WHERE location_id = :old AND source_id = :s"
                ),
                {"new": new_loc, "old": target, "s": source_id},
            )
        session.commit()
        logger.info("re-resolved {:,} jobs onto {:,} source(s)", total, len(plan))

        left = session.execute(
            text("SELECT count(*) FROM core.jobs WHERE location_id = :t"), {"t": target}
        ).scalar_one()
        logger.info("jobs still on the collapsed row: {:,}", left)
    return 0


if __name__ == "__main__":
    sys.exit(main())

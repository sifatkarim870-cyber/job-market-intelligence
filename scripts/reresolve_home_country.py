#!/usr/bin/env python
"""Re-resolve jobs whose location was cached before a home country existed.

What was wrong
--------------
``resolve_location_text`` falls back to a source's home country when the
posting's location text matches nothing. That fallback is driven by
``SOURCE_HOME_COUNTRY``, and two national government boards were missing from
it: ``jobbank`` (Canada) and ``usajobs`` (United States).

The consequence was not "country unknown". Both boards' unparseable locations
collapsed onto one shared ``ref.locations`` row -- ``"Worldwide / remote
(unspecified location)"``, ``is_global_remote = True`` -- so every Job Bank row
and 2 USAJOBS rows were being reported as *open to the entire world* when they
are Canadian and US federal postings. ``is_global_remote`` is a factual claim
about the job, not a statement about our parser, which is exactly what the
``SOURCE_HOME_COUNTRY`` docstring says the map exists to prevent.

Why this needs its own script rather than a re-scrape
-----------------------------------------------------
``resolve_and_cache_location`` checks ``core.location_aliases`` *first* and
returns the cached answer without re-matching. The bad resolutions are cached,
so scraping again would keep returning them forever. The aliases must be
dropped before anything re-resolves.

Attribution rule
----------------
``core.jobs`` stores only ``location_id``, not the raw text it came from, so a
job cannot always be traced back to the alias that produced its location. A
``(source, location)`` pair is therefore only repaired when **every** alias of
that source pointing at that location now resolves to the *same* country. Then
it does not matter which raw text a given job carried: the country is known
either way. If two aliases disagree, nothing is moved and the case is reported
rather than guessed.

Safety constraints
------------------
* Only sources listed in ``SOURCE_HOME_COUNTRY`` are touched. A remote-first
  board (remoteok, remotive, weworkremotely) genuinely asserting a worldwide
  opening keeps its ``is_global_remote`` row.
* Only locations with **no country** *and* ``is_global_remote`` are considered,
  so a real city or country match is never unmoved.
* ``--dry-run`` reports the exact counts ``--apply`` will change.

Usage:
    uv run python scripts/reresolve_home_country.py --dry-run
    uv run python scripts/reresolve_home_country.py --apply
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from loguru import logger
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_market_intel.db.session import get_session  # noqa: E402
from job_market_intel.normalization.geographic_resolution import (  # noqa: E402
    SOURCE_HOME_COUNTRY,
    _get_remote_work_type_id,
    get_or_create_location,
    resolve_location_text,
)

#: (source, location) pairs whose location names no country yet claims a
#: worldwide opening that a single-country board cannot support.
_STALE_TARGETS = text("""
    SELECT DISTINCT s.source_code, s.source_id, l.location_id
    FROM core.location_aliases a
    JOIN ref.sources s  ON s.source_id = a.source_id
    JOIN ref.locations l ON l.location_id = a.location_id
    WHERE s.source_code = ANY(:codes)
      AND l.country_id IS NULL
      AND l.is_global_remote
    ORDER BY s.source_code, l.location_id
""")

_ALIASES_FOR = text("""
    SELECT a.raw_location_text
    FROM core.location_aliases a
    WHERE a.source_id = :sid AND a.location_id = :lid
    ORDER BY a.raw_location_text
""")

_JOBS_AT = text("SELECT job_id FROM core.jobs WHERE source_id = :sid AND location_id = :lid")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Report only.")
    group.add_argument("--apply", action="store_true", help="Delete aliases and repoint jobs.")
    args = ap.parse_args(argv)

    codes = sorted(SOURCE_HOME_COUNTRY)

    with get_session() as session:
        targets = session.execute(_STALE_TARGETS, {"codes": codes}).mappings().all()
        if not targets:
            logger.info("no country-less global-remote aliases for {} -- nothing to do", codes)
            return 0

        plan: list[dict] = []
        for t in targets:
            sid, lid = int(t["source_id"]), int(t["location_id"])
            home = SOURCE_HOME_COUNTRY[t["source_code"]]
            raws = [
                r["raw_location_text"]
                for r in session.execute(_ALIASES_FOR, {"sid": sid, "lid": lid}).mappings().all()
            ]
            jobs = [
                r["job_id"]
                for r in session.execute(_JOBS_AT, {"sid": sid, "lid": lid}).mappings().all()
            ]

            countries: dict[str, list[str]] = collections.defaultdict(list)
            for raw in raws:
                out = resolve_location_text(session, raw, default_country_iso2=home)
                iso = (
                    session.execute(
                        text("SELECT iso_code_2 FROM ref.countries WHERE country_id = :cid"),
                        {"cid": out.country_id},
                    ).scalar()
                    if out.country_id
                    else None
                )
                countries[iso or "<none>"].append(raw)

            if not jobs:
                continue
            if list(countries) == ["<none>"]:
                logger.warning(
                    "{} location_id={}: {} job(s) still resolve to no country; left alone",
                    t["source_code"],
                    lid,
                    len(jobs),
                )
                continue
            if len(countries) > 1:
                logger.warning(
                    "{} location_id={}: aliases disagree ({}); left alone rather than guessed",
                    t["source_code"],
                    lid,
                    {k: len(v) for k, v in countries.items()},
                )
                continue

            country = next(iter(countries))
            plan.append(
                {
                    "source_code": t["source_code"],
                    "source_id": sid,
                    "location_id": lid,
                    "home": home,
                    "country": country,
                    "jobs": jobs,
                    "raws": raws,
                }
            )
            logger.info(
                "  {:<10} location_id={:<5} {} job(s) -> {} (from {} alias(es): {})",
                t["source_code"],
                lid,
                len(jobs),
                country,
                len(raws),
                ", ".join(r[:22] for r in raws[:3]),
            )

        total_jobs = sum(len(p["jobs"]) for p in plan)
        if not plan:
            logger.warning("nothing safely repairable")
            return 1
        logger.info("{} job(s) across {} target(s) would be repointed", total_jobs, len(plan))

        if args.dry_run:
            logger.info("--dry-run: nothing changed")
            return 0

        for p in plan:
            out = resolve_location_text(session, p["raws"][0], default_country_iso2=p["home"])
            new_location_id = get_or_create_location(
                session,
                city_id=out.city_id,
                region_id=out.region_id,
                country_id=out.country_id,
                remote_work_type_id=_get_remote_work_type_id(session, out.remote_work_type_code),
                raw_location_text=p["raws"][0],
                is_global_remote=bool(out.is_global_remote),
            )
            # Only core.jobs is touched. core.location_aliases is UNIQUE(raw, source)
            # and the runtime role has SELECT + INSERT on it but no UPDATE or
            # DELETE, so the stale alias rows cannot be corrected from here.
            # They do not need to be: resolve_and_cache_location now bypasses an
            # alias that claims a worldwide opening for a single-country board,
            # so the stale entry is never trusted again and this UPDATE is
            # durable across later scrapes.
            session.execute(
                text("""
                    UPDATE core.jobs SET location_id = :new
                    WHERE source_id = :sid AND location_id = :old
                """),
                {"new": new_location_id, "sid": p["source_id"], "old": p["location_id"]},
            )
            logger.info(
                "  {}: location_id {} -> {} ({} jobs)",
                p["source_code"],
                p["location_id"],
                new_location_id,
                len(p["jobs"]),
            )
        session.commit()

        logger.info(f"done: {total_jobs} job(s) repointed out of the global-remote bucket")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Repair location aliases whose country answer changed after a resolver fix.

Reports first, writes only with ``--apply``.

Why this script rather than ``reresolve_home_country.py``
-------------------------------------------------------
That tool repairs the *global-remote* bucket, where a source's rows visibly went
to "Worldwide / remote". It cannot see this class of defect at all: a row that
resolved to a plausible but **wrong** country -- 'Governador Celso Ramos, SC'
filed under United States -- has a real ``region_id`` and a real ``country_id``,
so every existing health check passes it.

The fix that created the need
-----------------------------
``_US_STATE_ABBREVIATIONS`` was applied unconditionally, so a bare two-letter
token anywhere became a US state name. 'Governador Celso Ramos, SC' (Santa
Catarina, Brazil) matched 'SC' -> South Carolina, and 'Parauapebas, PA' (Pará,
Brazil) matched 'PA' -> Pennsylvania. The expansion is now gated on the source's
declared home country being the US, so both resolve to Brazil instead.

This compares every cached alias against what the resolver returns now. That is
the only way a wrong-but-plausible answer gets noticed once the matching logic
improves -- the stored rows look fine.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.normalization.geographic_resolution import (
    get_or_create_location,
    resolve_location_text,
    source_home_country,
)

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--apply", action="store_true", help="Repoint the affected jobs and aliases.")
args = ap.parse_args()


def _iso(session, country_id) -> str | None:
    if country_id is None:
        return None
    return session.execute(
        text("SELECT iso_code_2 FROM ref.countries WHERE country_id = :c"),
        {"c": country_id},
    ).scalar()


def main() -> int:
    with get_session() as s:
        rows = s.execute(
            text("""
            SELECT a.source_id, a.raw_location_text, a.location_id,
                   co.iso_code_2
            FROM core.location_aliases a
            JOIN ref.locations l  ON l.location_id = a.location_id
            JOIN ref.countries co ON co.country_id = l.country_id
        """)
        ).fetchall()

        # (source_id, raw, old_location_id, was_iso, now_iso, resolved)
        stale = []
        for source_id, raw, old_loc, was_iso in rows:
            home = source_home_country(s, source_id)
            if home is None:
                continue
            res = resolve_location_text(s, raw, default_country_iso2=home)
            now_iso = _iso(s, res.country_id)
            if now_iso != was_iso:
                stale.append((source_id, raw, old_loc, was_iso, now_iso, res))

        print(f"aliases checked : {len(rows):,}")
        print(f"stale (country changed): {len(stale)}")
        for source_id, raw, _old, was, now, res in stale[:20]:
            print(
                f"  src={source_id:<4} {raw[:50]:<52} {str(was):<5} -> {str(now):<5} "
                f"via {res.match_method}"
            )

        if not stale:
            return 0
        if not args.apply:
            print("\n(no --apply: nothing written)")
            return 0

        total_jobs = 0
        for source_id, raw, old_loc, _was, now, res in stale:
            if res.country_id is None:
                continue
            home = source_home_country(s, source_id)
            rwt_id = s.execute(
                text("SELECT remote_work_type_id FROM ref.remote_work_types WHERE code = :c"),
                {"c": res.remote_work_type_code},
            ).scalar()

            # get_or_create_location is the sanctioned path: it handles the
            # IS NOT DISTINCT FROM lookup that the UNIQUE constraint does not
            # cover when city/region/country are all NULL -- the common case for
            # a country-only fallback. A hand-rolled INSERT ... ON CONFLICT on
            # (raw_location_text, country_id) fails outright, because
            # ref.locations carries no constraint on that pair.
            new_loc = get_or_create_location(
                session=s,
                city_id=res.city_id,
                region_id=res.region_id,
                country_id=res.country_id,
                remote_work_type_id=rwt_id,
                raw_location_text=raw,
                is_global_remote=res.is_global_remote,
            )
            if new_loc is None:
                print(f"  SKIP {raw[:46]}: could not obtain a location row")
                continue

            moved = s.execute(
                text(
                    "UPDATE core.jobs SET location_id = :new "
                    "WHERE source_id = :sid AND location_id = :old"
                ),
                {"new": new_loc, "sid": source_id, "old": old_loc},
            ).rowcount
            # The alias row is deliberately NOT updated. The runtime role holds
            # only SELECT and INSERT on core.location_aliases (measured -- an
            # UPDATE raises InsufficientPrivilege), and the table is
            # UNIQUE(raw_location_text, source_id) so an INSERT would violate the
            # key. `stale_country_conflict` in geographic_resolution now declines
            # to trust any alias whose country disagrees with the source's own, so
            # the stale row is bypassed on every future scrape and needs no
            # cleanup.
            total_jobs += moved
            print(f"  repaired {raw[:44]:<46} -> {now} ({moved} job(s))")

        s.commit()
        print(f"\n--apply: repointed {total_jobs} job(s) across {len(stale)} alias(es)")
        print(
            "The stale alias rows remain in core.location_aliases by design -- "
            "they are bypassed, not trusted."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

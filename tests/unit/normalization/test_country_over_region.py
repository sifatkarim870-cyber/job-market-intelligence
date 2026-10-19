"""A country name must outrank a same-named US state.

The bug this prevents
---------------------
``Georgia`` is the only country name in the world that is also the name of a US
state, and it is the only entry in ``ref.regions`` that collides with a
``ref.countries.country_name`` -- measured, not assumed:

    SELECT c.country_name FROM ref.countries c
    JOIN ref.regions r ON r.country_id = (SELECT country_id FROM ref.countries
                                         WHERE iso_code_2 = 'US')
    WHERE lower(c.country_name) = lower(r.region_name);
    -- 1 row: Georgia

``_match_segment`` tries city, then region, then country, so the **region won
every time**. Measured on the corpus 2026-10-19: **539 rows** whose location
string was literally "Georgia" were attributed to the **United States** -- 537
of them from ``hrge``, a Georgian board, plus one each from ``builtin`` and
``greenhouse``.

Why a country beats a region
----------------------------
A bare country name is a stronger signal than a bare region name. On its own,
"Georgia" means the country. Nothing about the string suggests a US state: no
state abbreviation, no city, no ZIP.

The gate
--------
Flipping this unconditionally would break the 537 genuinely-correct US rows --
on a **US** board, "Georgia" means Atlanta's state essentially every time. So
the preference is gated exactly like :func:`_us_abbreviation_allowed`, on the
source's declared home country.

An **unknown** home country keeps the old behaviour, for the same reason
``_us_abbreviation_allowed`` does: this module does not change what a source
with no ``SOURCE_HOME_COUNTRY`` entry resolves to. Every registered source now
declares one, so that branch is close to dead and is left alone on purpose.

Run with:  uv run pytest tests/unit/normalization/test_country_over_region.py -q
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from job_market_intel.normalization.geographic_resolution import (
    _country_outranks_region,
    resolve_location_text,
)

#: Hardcoded on purpose, the same idiom as
#: tests/unit/corpus/test_merge_incoming_shards.py.
#:
#: NOT ``job_market_intel.db.session.get_session()``, which resolves the DSN
#: from the environment. tests/integration/test_database.py's
#: ``_hermetic_dsn_env`` clears ``DATABASE_URL``, ``CI_DATABASE_URL``,
#: ``CI_CONTAINER_DB`` and ``GITHUB_ACTIONS`` to neutralise DSN lookup for its
#: own purposes, and that reaches every test that runs after it -- which is
#: exactly this file, since tests/integration/ sorts before tests/unit/.
#: Measured: all ten DB-touching integration test files break this module, and
#: none of them has anything to do with Georgia.
DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"


@pytest.fixture(scope="module")
def session():
    try:
        eng = create_engine(DSN, connect_args={"connect_timeout": 5})
        with Session(eng) as s:
            s.execute(text("SELECT 1"))
            yield s
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local Postgres unavailable: {str(exc)[:80]}")


def _resolve(session, raw: str, home: str | None) -> tuple[str | None, str | None]:
    r = resolve_location_text(session, raw, default_country_iso2=home)
    if r.country_id is None:
        return None, r.match_method
    iso = session.execute(
        text("SELECT iso_code_2 FROM ref.countries WHERE country_id = :i"),
        {"i": r.country_id},
    ).scalar()
    return iso, r.match_method


class TestTheCollisionIsReal:
    def test_georgia_is_the_only_country_that_collides_with_a_us_state(self, session):
        rows = (
            session.execute(
                text("""
            SELECT c.country_name, c.iso_code_2
            FROM ref.countries c
            JOIN ref.regions r
              ON r.country_id = (SELECT country_id FROM ref.countries
                                 WHERE iso_code_2 = 'US')
            WHERE lower(c.country_name) = lower(r.region_name)
        """)
            )
            .mappings()
            .all()
        )
        assert [r["iso_code_2"] for r in rows] == ["GE"], (
            "a new country/region name collision appeared; this file asserts the "
            f"Georgia case is the only one, and now there are {[dict(r) for r in rows]}"
        )

    def test_both_targets_exist(self, session):
        """Guard against the fixture drifting: GE country and a US 'Georgia' region."""
        assert (
            session.execute(
                text("SELECT count(*) FROM ref.countries WHERE country_name = 'Georgia'")
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                text("""
            SELECT count(*) FROM ref.regions r
            JOIN ref.countries c ON c.country_id = r.country_id
            WHERE c.iso_code_2 = 'US' AND r.region_name = 'Georgia'
        """)
            ).scalar_one()
            == 1
        )


class TestNonUSBoardsGetTheCountry:
    @pytest.mark.parametrize("home", ["GE", "HR", "BR", "ZA", "KE"])
    def test_bare_georgia_is_the_country(self, session, home):
        iso, method = _resolve(session, "Georgia", home)
        assert iso == "GE", f"home={home}: got {iso} via {method}"
        assert method == "country_exact"

    def test_other_us_state_names_are_untouched(self, session):
        """California and Texas are states, not countries. Nothing may change."""
        for raw in ("California", "Texas"):
            iso, method = _resolve(session, raw, "GE")
            assert iso == "US", f"{raw} became {iso}"
            assert method == "region_exact"

    def test_a_georgian_city_still_wins_over_the_country(self, session):
        iso, _ = _resolve(session, "Tbilisi", "GE")
        assert iso == "GE"
        for city in ("Tbilisi", "Batumi", "Kutaisi"):
            resolved = resolve_location_text(session, city, default_country_iso2="GE")
            assert resolved.city_id is not None, city

    def test_city_comma_georgia_still_resolves_the_city(self, session):
        """'Atlanta, Georgia' must stay in the US -- the city carries it there."""
        iso, _ = _resolve(session, "Atlanta, Georgia", "GE")
        assert iso == "US"


class TestUSBoardsKeepTheState:
    @pytest.mark.parametrize("home", ["US"])
    def test_bare_georgia_is_the_state_on_a_us_board(self, session, home):
        iso, method = _resolve(session, "Georgia", home)
        assert iso == "US", f"got {iso} via {method}"
        assert method == "region_exact"

    def test_unknown_home_country_keeps_the_old_behaviour(self, session):
        """Deliberate: this module does not change what unregistered sources get.

        Same reasoning as ``_us_abbreviation_allowed(None) is True``.
        """
        iso, method = _resolve(session, "Georgia", None)
        assert iso == "US"
        assert method == "region_exact"

    def test_the_gate_helper_agrees_with_the_resolver(self, session):
        assert _country_outranks_region(session, "georgia", "GE") is not None
        assert _country_outranks_region(session, "georgia", "US") is None
        assert _country_outranks_region(session, "georgia", None) is None

    def test_the_helper_returns_none_for_a_name_that_is_not_a_country(self, session):
        assert _country_outranks_region(session, "california", "GE") is None
        assert _country_outranks_region(session, "not a place", "GE") is None

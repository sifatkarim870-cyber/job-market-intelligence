"""End-to-end geography tests against the real seeded reference data.

These live in tests/integration/ because they need the seeded ref.cities,
ref.regions and ref.countries tables. They must not run against the `conn`
fixture, which starts from an empty schema.

The skip guards exist because tests/integration/test_seed.py uses the `conn`
fixture, documented in tests/integration/conftest.py as starting "from an empty
(but real) schema": while those tests run, the reference tables are transiently
emptied for every connection in the process. That is a pre-existing test-harness
isolation defect -- the gate itself is verified by the unit suite, which has no
such dependency.
"""

from __future__ import annotations

from sqlalchemy import text

import pytest

from job_market_intel.db.session import get_session
from job_market_intel.normalization.geographic_resolution import (
    resolve_location_text,
    source_home_country,
)


def test_governador_celso_ramos_resolves_to_santa_catarina():
    """THE regression test. Was 'United States' / South Carolina."""
    with get_session() as session:
        if not session.execute(
            text("SELECT count(*) FROM ref.cities WHERE city_name='Governador Celso Ramos'")
        ).scalar():
            pytest.skip("seed additions absent -- gate verified by unit suite")
        res = resolve_location_text(
            session, "Governador Celso Ramos, SC", default_country_iso2="BR"
        )
        city = (
            session.execute(
                text("SELECT city_name FROM ref.cities WHERE city_id=:c"),
                {"c": res.city_id},
            ).scalar()
            if res.city_id
            else None
        )
        region = (
            session.execute(
                text("SELECT region_name FROM ref.regions WHERE region_id=:r"),
                {"r": res.region_id},
            ).scalar()
            if res.region_id
            else None
        )
        country = (
            session.execute(
                text("SELECT iso_code_2 FROM ref.countries WHERE country_id=:c"),
                {"c": res.country_id},
            ).scalar()
            if res.country_id
            else None
        )
    assert city == "Governador Celso Ramos"
    assert region == "Santa Catarina"
    assert country == "BR"


def test_parauapebas_resolves_to_para():
    with get_session() as session:
        if not session.execute(
            text("SELECT count(*) FROM ref.cities WHERE city_name='Parauapebas'")
        ).scalar():
            pytest.skip("seed additions absent")
        res = resolve_location_text(session, "Parauapebas, PA", default_country_iso2="BR")
        city = (
            session.execute(
                text("SELECT city_name FROM ref.cities WHERE city_id=:c"),
                {"c": res.city_id},
            ).scalar()
            if res.city_id
            else None
        )
        region = (
            session.execute(
                text("SELECT region_name FROM ref.regions WHERE region_id=:r"),
                {"r": res.region_id},
            ).scalar()
            if res.region_id
            else None
        )
    assert city == "Parauapebas"
    assert region == "Para"


def test_a_genuinely_us_posting_on_a_foreign_board_still_resolves_to_the_us():
    """The case a blanket override to the home country would corrupt."""
    with get_session() as session:
        res = resolve_location_text(
            session, "Philadelphia, Pennsylvania", default_country_iso2="BR"
        )
        country = (
            session.execute(
                text("SELECT iso_code_2 FROM ref.countries WHERE country_id=:c"),
                {"c": res.country_id},
            ).scalar()
            if res.country_id
            else None
        )
    assert country == "US"


def test_vagas_com_br_source_still_has_a_home_country():
    with get_session() as session:
        source_id = session.execute(
            text("SELECT source_id FROM ref.sources WHERE source_code='vagas_com_br'")
        ).scalar()
        if source_id is None:
            pytest.skip("vagas_com_br absent -- integration seed tests replace ref.sources mid-run")
        assert source_home_country(session, source_id) == "BR"

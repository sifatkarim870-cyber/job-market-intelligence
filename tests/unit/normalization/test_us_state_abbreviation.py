"""A two-letter token must not become a US state unless the source IS the US.

The bug
-------
``_US_STATE_ABBREVIATIONS`` was applied unconditionally, so any two-letter token
anywhere in the corpus was expanded to a US state name before the region lookup.
Measured 2026-10-18 on Vagas.com.br (Brazil)::

    raw_location_text                region_id=40   country='United States'
    'Governador Celso Ramos, SC'

``Governador Celso Ramos`` is a municipality in **Santa Catarina, Brazil**, and
``SC`` is its state code. The city matched nothing at the time, so the comma
fallback reached the state part, expanded ``SC`` to ``South Carolina``, and filed
a Brazilian job under the United States. ``'Parauapebas, PA'`` hit the same path
via ``PA`` -> Pennsylvania.

Several of the table's keys are subdivision codes in other countries: ``SC``
(Santa Catarina), ``GA`` (the country Georgia), ``LA`` (Liaoning), ``IN``
(India), ``ME`` (Montenegro), ``MD`` (Moldova), ``AL`` (Albania). The gate means
none of them can win from the wrong country's board.

Why these tests use no database
-------------------------------
They assert *which string reaches the region lookup*, which is precisely what
the fix changes and needs no reference data to observe.

That matters for more than tidiness. ``tests/integration/test_seed.py`` uses the
``conn`` fixture, documented in ``tests/integration/conftest.py`` as starting
"from an empty (but real) schema" -- so while integration seed tests run, the
reference tables are transiently empty for every other connection in the process.
A test in ``tests/unit/`` that reads live reference data therefore passes alone
and fails in the full suite depending on ordering. That is a property of the
reference data being absent, not of the code under test.

The end-to-end resolution against real seeded data lives in
``tests/integration/test_us_state_abbreviation_e2e.py``.

Run with:  uv run pytest tests/unit/normalization/test_us_state_abbreviation.py -q
"""

from __future__ import annotations

import pytest

import job_market_intel.normalization.geographic_resolution as geo
from job_market_intel.normalization.geographic_resolution import (
    _US_STATE_ABBREVIATIONS,
    _us_abbreviation_allowed,
)


class TestGate:
    """The gate itself -- pure logic, no I/O."""

    def test_a_us_source_may_expand(self) -> None:
        assert _us_abbreviation_allowed("US") is True

    def test_an_unknown_source_may_expand(self) -> None:
        """Preserves existing behaviour for sources with no home country.

        Deliberate, not an oversight: an unregistered US board must not silently
        start losing its "Springfield, IL" postings because of a gate added for
        Brazil.
        """
        assert _us_abbreviation_allowed(None) is True

    def test_a_foreign_source_may_not(self) -> None:
        for iso in ("BR", "AF", "GH", "RW", "AO", "GB", "CA"):
            assert _us_abbreviation_allowed(iso) is False

    def test_the_gate_is_case_insensitive(self) -> None:
        assert _us_abbreviation_allowed("us") is True
        assert _us_abbreviation_allowed("Us") is True

    def test_blank_reads_as_unknown_not_as_foreign(self) -> None:
        assert _us_abbreviation_allowed("") is True


class TestTheTableIsTheHazard:
    """Pins the fact that makes the gate necessary, so it can't be "cleaned up"."""

    @pytest.mark.parametrize(
        ("code", "us_state"),
        [
            ("sc", "South Carolina"),
            ("pa", "Pennsylvania"),
            ("ga", "Georgia"),
            ("la", "Louisiana"),
            ("in", "Indiana"),
            ("me", "Maine"),
            ("md", "Maryland"),
            ("al", "Alabama"),
        ],
    )
    def test_ambiguous_codes_expand_to_a_us_state(self, code: str, us_state: str) -> None:
        assert _US_STATE_ABBREVIATIONS[code] == us_state

    def test_the_table_is_lowercase_keys(self) -> None:
        """A key lookup with an unnormalized token silently misses."""
        assert all(k == k.lower() for k in _US_STATE_ABBREVIATIONS)


class TestWhatReachesTheRegionLookup:
    """THE regression: which string is looked up, per source country.

    ``_match_region`` is stubbed to record the name it is handed. That is the
    exact decision the fix changes, and observing it needs no reference data --
    so these tests are immune to the integration suite truncating ref.regions.
    """

    @pytest.fixture()
    def looked_up(self, monkeypatch):
        seen: list[str] = []

        def _record(session, name):
            seen.append(name)
            return None  # "nothing matched" -- the interesting case

        monkeypatch.setattr(geo, "_match_region", _record)
        monkeypatch.setattr(geo, "_match_city", lambda session, name: None)
        monkeypatch.setattr(geo, "_match_country", lambda session, name: None)
        return seen

    def test_a_foreign_board_looks_up_the_raw_token(self, looked_up) -> None:
        """'Governador Celso Ramos, SC' must NOT become 'south carolina'."""
        geo._match_comma_fallback(None, "governador celso ramos, sc", "BR")
        assert looked_up == ["sc"]

    def test_a_us_board_looks_up_the_expanded_state(self, looked_up) -> None:
        geo._match_comma_fallback(None, "springfield, il", "US")
        assert looked_up == ["illinois"]

    def test_an_unknown_board_keeps_the_old_behaviour(self, looked_up) -> None:
        """No declared home country -> unchanged, so nothing silently regresses."""
        geo._match_comma_fallback(None, "springfield, il", None)
        assert looked_up == ["illinois"]

    @pytest.mark.parametrize(
        ("raw", "default_country"), [("x, pa", "BR"), ("x, sc", "GH"), ("x, in", "AF")]
    )
    def test_no_foreign_board_ever_expands(self, looked_up, raw: str, default_country: str) -> None:
        geo._match_comma_fallback(None, raw, default_country)
        assert len(looked_up) == 1
        assert looked_up[0] == raw.split(",")[1].strip()

    def test_a_full_word_region_still_works_for_any_source(self, looked_up) -> None:
        """Gating must not block a region named in full -- only the abbreviation."""
        geo._match_comma_fallback(None, "baghlan, kabul", "AF")
        assert looked_up == ["kabul"]


class TestCityWinsRegardless:
    """The city part is consulted first, which is why the gate is safe.

    ``"Philadelphia, Pennsylvania"`` is a real US listing on the Brazilian board.
    It resolves on the city, before the state part is ever considered -- so a
    gate on the abbreviation cannot force it to Brazil. This is the case a blanket
    "everything on a foreign board is in the source's country" override would
    have silently corrupted.
    """

    def test_a_known_city_is_returned_before_the_state_part(self, monkeypatch) -> None:
        monkeypatch.setattr(geo, "_match_region", lambda session, name: None)

        def _city(session, name):
            if name.strip().lower() == "philadelphia":
                return (4242, 40, 1)  # (city_id, region_id, country_id)
            return None

        monkeypatch.setattr(geo, "_match_city", _city)
        match = geo._match_comma_fallback(None, "philadelphia, pennsylvania", "BR")
        assert match is not None
        assert match.country_id == 1  # US, not BR
        assert match.city_id == 4242

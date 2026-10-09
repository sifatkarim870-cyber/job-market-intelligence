"""Unit tests for normalization.geographic_resolution.

Mirrors tests/unit/normalization/test_company_resolution.py's approach:
DB-touching functions get a mocked Session whose execute() branches on
SQL substring + bound params, not call order. split_location_segments
and the prefix/global-phrase handling inside resolve_location_text are
exercised directly since they're what actually decides city > region >
country > global > unmatched specificity -- the part of this module most
likely to regress silently.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from job_market_intel.normalization.geographic_resolution import (
    ResolvedLocation,
    get_or_create_location,
    resolve_and_cache_location,
    resolve_location_text,
    split_location_segments,
)


class TestSplitLocationSegments:
    def test_single_segment_no_semicolon(self) -> None:
        assert split_location_segments("Worldwide") == ["Worldwide"]

    def test_multi_segment_wwr_style(self) -> None:
        assert split_location_segments("Anywhere in the World; Argentina; Texas") == [
            "Anywhere in the World",
            "Argentina",
            "Texas",
        ]

    def test_drops_empty_segments(self) -> None:
        assert split_location_segments("USA; ; Canada") == ["USA", "Canada"]

    def test_strips_whitespace(self) -> None:
        assert split_location_segments("  Remote - US  ") == ["Remote - US"]


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    return result


class _CityRow:
    def __init__(self, city_id: int, region_id: int | None, country_id: int) -> None:
        self.city_id = city_id
        self.region_id = region_id
        self.country_id = country_id


class _RegionRow:
    def __init__(self, region_id: int, country_id: int) -> None:
        self.region_id = region_id
        self.country_id = country_id


def _mock_geo_session(
    city_rows: list | None = None,
    region_rows: list | None = None,
    country_id: int | None = None,
    remote_work_type_id: int | None = 6,
) -> MagicMock:
    """A fake Session for resolve_location_text/_match_* -- branches on
    which reference table the SQL targets. city_rows/region_rows default
    to no match (empty list); country_id defaults to no match (None).
    """
    session = MagicMock()

    def _execute(stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM ref.cities" in sql:
            return _rows_result(city_rows or [])
        if "FROM ref.regions" in sql:
            return _rows_result(region_rows or [])
        if "FROM ref.countries" in sql:
            return _scalar_result(country_id)
        if "FROM ref.remote_work_types" in sql:
            return _scalar_result(remote_work_type_id)
        return _scalar_result(None)

    session.execute.side_effect = _execute
    return session


class TestResolveLocationText:
    def test_explicit_global_assertion(self) -> None:
        session = _mock_geo_session()
        resolved = resolve_location_text(session, "Worldwide")
        assert resolved.remote_work_type_code == "remote_global"
        assert resolved.is_global_remote is True
        assert resolved.match_method == "global_assertion"
        assert resolved.city_id is None
        assert resolved.country_id is None

    def test_unmatched_falls_back_to_global_but_not_asserted(self) -> None:
        session = _mock_geo_session()  # nothing matches anything
        resolved = resolve_location_text(session, "Narnia")
        assert resolved.remote_work_type_code == "remote_global"
        assert resolved.is_global_remote is False
        assert resolved.match_method == "fallback_unmatched"

    def test_country_match_via_alias_map(self) -> None:
        # "USA" isn't a literal ref.countries.country_name row (that's
        # "United States") -- this proves _COUNTRY_NAME_ALIASES is
        # actually consulted, not just the raw string.
        session = _mock_geo_session(country_id=1)
        resolved = resolve_location_text(session, "USA")
        assert resolved.country_id == 1
        assert resolved.remote_work_type_code == "remote_country"
        assert resolved.match_method == "country_exact"
        assert resolved.is_global_remote is False

    def test_remote_prefix_is_stripped_before_matching(self) -> None:
        session = _mock_geo_session(country_id=1)
        resolved = resolve_location_text(session, "Remote - US")
        assert resolved.country_id == 1
        assert resolved.match_method == "country_exact"

    def test_city_match_beats_country_match_across_segments(self) -> None:
        # Regression case: We Work Remotely's multi-segment strings must
        # keep the MOST SPECIFIC match, not the first segment (Decision
        # #4 of the confirmed Step 28 proposal).
        session = _mock_geo_session(
            city_rows=[_CityRow(city_id=55, region_id=None, country_id=3)],
            country_id=2,
        )
        resolved = resolve_location_text(session, "Anywhere in the World; France; Berlin")
        assert resolved.city_id == 55
        assert resolved.country_id == 3
        assert resolved.remote_work_type_code == "remote_city"
        assert resolved.match_method == "city_exact"

    def test_region_match_when_no_city_matches(self) -> None:
        session = _mock_geo_session(region_rows=[_RegionRow(region_id=10, country_id=1)])
        resolved = resolve_location_text(session, "Texas")
        assert resolved.region_id == 10
        assert resolved.country_id == 1
        # NOT "remote_region" -- confirmed against seed/remote_work_types.py:
        # that code means a MULTI-COUNTRY bloc (EU/LATAM/APAC), a different
        # concept from a ref.regions row (a state/province within ONE
        # country). A state/province match still buckets as
        # "remote_country" -- see resolve_location_text's inline comment.
        assert resolved.remote_work_type_code == "remote_country"
        assert resolved.match_method == "region_exact"

    def test_ambiguous_city_name_falls_through_rather_than_guessing(self) -> None:
        # Two seeded cities share this name -- _match_city must treat
        # that as "no match" (falls through toward country/global),
        # never picking one arbitrarily.
        session = _mock_geo_session(
            city_rows=[
                _CityRow(city_id=1, region_id=None, country_id=1),
                _CityRow(city_id=2, region_id=None, country_id=2),
            ],
        )
        resolved = resolve_location_text(session, "Cambridge")
        assert resolved.city_id is None
        assert resolved.match_method == "fallback_unmatched"


def _precise_geo_session(
    *,
    city_matches: dict[str, list] | None = None,
    region_matches: dict[str, list] | None = None,
    country_matches: dict[str, int] | None = None,
    remote_work_type_id: int | None = 6,
) -> MagicMock:
    """A fake Session for the comma-fallback tests specifically -- unlike
    _mock_geo_session (which returns the same result regardless of the
    bound :name/:code param), this branches on the EXACT normalized
    string queried. Needed here because these tests must distinguish
    "the whole segment found nothing" from "the city-part-only retry
    found something" -- something the coarser table-only mock can't do.
    """
    city_matches = city_matches or {}
    region_matches = region_matches or {}
    country_matches = country_matches or {}
    session = MagicMock()

    def _execute(stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if "FROM ref.cities" in sql:
            return _rows_result(city_matches.get(params.get("name"), []))
        if "FROM ref.regions" in sql:
            return _rows_result(region_matches.get(params.get("name"), []))
        if "FROM ref.countries" in sql:
            key = params.get("name") or params.get("code")
            return _scalar_result(country_matches.get(key))
        if "FROM ref.remote_work_types" in sql:
            return _scalar_result(remote_work_type_id)
        return _scalar_result(None)

    session.execute.side_effect = _execute
    return session


class TestCommaFallback:
    """Regression coverage for the real bug this fallback fixes: Indeed's
    "City, ST"/"City, ST ZIP (neighborhood)" location strings never
    exactly matched a bare seeded city name, so nearly every Indeed job
    was silently collapsing onto one shared 'fallback_unmatched' row --
    see geographic_resolution.py's module docstring and
    db/scrape_queue_repository.py-adjacent chat history for the full
    real-run diagnosis this came from.
    """

    def test_city_comma_state_abbreviation_resolves_to_city(self) -> None:
        session = _precise_geo_session(
            city_matches={"san francisco": [_CityRow(city_id=10, region_id=20, country_id=1)]}
        )
        resolved = resolve_location_text(session, "San Francisco, CA")
        assert resolved.city_id == 10
        assert resolved.match_method == "city_exact"

    def test_hybrid_prefix_and_comma_state_both_handled_together(self) -> None:
        session = _precise_geo_session(
            city_matches={"austin": [_CityRow(city_id=11, region_id=21, country_id=1)]}
        )
        resolved = resolve_location_text(session, "Hybrid work in Austin, TX")
        assert resolved.city_id == 11
        assert resolved.match_method == "city_exact"

    def test_remote_work_in_prefix_alone_is_stripped(self) -> None:
        # Isolates the "work in" fix from the comma fallback above --
        # confirms the prefix stripper itself handles this phrasing, not
        # just that the combination happens to work.
        session = _precise_geo_session(country_matches={"germany": 40})
        resolved = resolve_location_text(session, "Remote work in Germany")
        assert resolved.country_id == 40
        assert resolved.match_method == "country_exact"

    def test_zip_and_parenthetical_neighborhood_both_stripped(self) -> None:
        session = _precise_geo_session(
            city_matches={"san francisco": [_CityRow(city_id=10, region_id=20, country_id=1)]}
        )
        resolved = resolve_location_text(
            session, "San Francisco, CA 94105 ( Financial District/South Beach area )"
        )
        assert resolved.city_id == 10
        assert resolved.match_method == "city_exact"

    def test_unseeded_city_falls_back_to_state_abbreviation_as_region(self) -> None:
        # City part ("faketown") isn't seeded, but the state abbreviation
        # ("TX" -> "Texas") should still resolve at region level rather
        # than giving up entirely.
        session = _precise_geo_session(
            region_matches={"texas": [_RegionRow(region_id=30, country_id=1)]}
        )
        resolved = resolve_location_text(session, "Faketown, TX")
        assert resolved.region_id == 30
        assert resolved.match_method == "region_exact"

    def test_city_comma_country_resolves_via_country_fallback(self) -> None:
        # Non-US shape: "City, Country" where the city itself isn't
        # seeded but the country part is -- proves the comma fallback
        # isn't US-state-specific.
        session = _precise_geo_session(country_matches={"germany": 40})
        resolved = resolve_location_text(session, "Faketown, Germany")
        assert resolved.country_id == 40
        assert resolved.match_method == "country_exact"

    def test_comma_string_with_no_match_anywhere_still_falls_back_unmatched(self) -> None:
        session = _precise_geo_session()  # nothing seeded matches anything
        resolved = resolve_location_text(session, "Nowhereville, ZZ")
        assert resolved.match_method == "fallback_unmatched"

    def test_comma_fallback_never_overrides_a_whole_segment_match(self) -> None:
        # If the UNMODIFIED segment already matches something (e.g. a
        # future source seeds a city literally named "Some City, Inc"),
        # the comma fallback must never run and override it.
        session = _precise_geo_session(
            city_matches={
                "some city, inc": [_CityRow(city_id=99, region_id=None, country_id=1)],
                "some city": [_CityRow(city_id=1, region_id=None, country_id=2)],
            }
        )
        resolved = resolve_location_text(session, "Some City, Inc")
        assert resolved.city_id == 99  # the whole-segment match, not the comma-split one


class TestGetOrCreateLocation:
    def test_reuses_existing_row_when_found(self) -> None:
        session = MagicMock()
        session.execute.return_value = _scalar_result(777)

        location_id = get_or_create_location(
            session,
            city_id=None,
            region_id=None,
            country_id=None,
            remote_work_type_id=6,
            raw_location_text="Worldwide",
            is_global_remote=True,
        )

        assert location_id == 777
        # Only the SELECT should have run -- no INSERT when a match was found.
        assert session.execute.call_count == 1

    def test_inserts_new_row_when_no_existing_combo_matches(self) -> None:
        session = MagicMock()
        calls: list[str] = []

        def _execute(stmt, params=None):
            sql = " ".join(str(stmt).split())
            calls.append(sql)
            if sql.startswith("SELECT location_id FROM ref.locations"):
                return _scalar_result(None)
            if sql.startswith("INSERT INTO ref.locations"):
                return _scalar_result(42)
            raise AssertionError(f"unexpected SQL: {sql}")

        session.execute.side_effect = _execute

        location_id = get_or_create_location(
            session,
            city_id=None,
            region_id=None,
            country_id=5,
            remote_work_type_id=4,
            raw_location_text="India",
            is_global_remote=False,
        )

        assert location_id == 42
        assert any(sql.startswith("INSERT INTO ref.locations") for sql in calls)

    def test_lookup_uses_is_not_distinct_from_not_equals(self) -> None:
        # Regression guard for the NULL-vs-NULL dedup bug described in
        # the module docstring: plain "=" would never match an existing
        # all-NULL combo, causing unbounded duplicate rows.
        session = MagicMock()
        session.execute.return_value = _scalar_result(1)

        get_or_create_location(
            session,
            city_id=None,
            region_id=None,
            country_id=None,
            remote_work_type_id=6,
            raw_location_text="Narnia",
            is_global_remote=False,
        )

        select_sql = " ".join(str(session.execute.call_args.args[0]).split())
        assert "IS NOT DISTINCT FROM" in select_sql


class TestResolveAndCacheLocation:
    def test_none_raw_text_returns_none_without_querying(self) -> None:
        session = MagicMock()
        assert resolve_and_cache_location(session, None, source_id=1) is None
        session.execute.assert_not_called()

    def test_blank_raw_text_returns_none_without_querying(self) -> None:
        session = MagicMock()
        assert resolve_and_cache_location(session, "   ", source_id=1) is None
        session.execute.assert_not_called()

    def test_cache_hit_short_circuits_full_resolution(self) -> None:
        session = MagicMock()
        session.execute.return_value = _scalar_result(123)

        location_id = resolve_and_cache_location(session, "Remote - US", source_id=1)

        assert location_id == 123
        # Only the cache SELECT should have run.
        assert session.execute.call_count == 1
        sql = " ".join(str(session.execute.call_args.args[0]).split())
        assert sql.startswith("SELECT location_id FROM core.location_aliases")

    def test_cache_miss_resolves_and_writes_alias_row(self) -> None:  # noqa: C901 - fake DB router
        session = MagicMock()
        calls: list[str] = []

        def _execute(stmt, params=None):
            sql = " ".join(str(stmt).split())
            calls.append(sql)
            if sql.startswith("SELECT location_id FROM core.location_aliases"):
                return _scalar_result(None)  # cache miss
            if "FROM ref.cities" in sql:
                return _rows_result([])
            if "FROM ref.regions" in sql:
                return _rows_result([])
            if "FROM ref.countries" in sql:
                return _scalar_result(None)  # unmatched -> fallback global
            if "FROM ref.sources" in sql:
                # resolve_and_cache_location looks the source's home country up
                # before falling back. "remoteok" is deliberately NOT in
                # SOURCE_HOME_COUNTRY, so this test keeps exercising the
                # unmatched -> remote_global path unchanged.
                return _scalar_result("remoteok")
            if "FROM ref.remote_work_types" in sql:
                return _scalar_result(9)
            if sql.startswith("SELECT location_id FROM ref.locations"):
                return _scalar_result(None)  # no existing combo
            if sql.startswith("INSERT INTO ref.locations"):
                return _scalar_result(500)
            if sql.startswith("INSERT INTO core.location_aliases"):
                return MagicMock()
            raise AssertionError(f"unexpected SQL: {sql}")

        session.execute.side_effect = _execute

        location_id = resolve_and_cache_location(session, "Narnia", source_id=2)

        assert location_id == 500
        assert any(sql.startswith("INSERT INTO core.location_aliases") for sql in calls)

    def test_unresolvable_city_on_single_country_board_uses_source_country(self):  # noqa: C901
        """A national board's unparseable city must not become "worldwide".

        jobvision's 390 aliases are all Persian ("تهران, تهران"), which the
        English-only seed cannot match. Before SOURCE_HOME_COUNTRY existed,
        all 60,982 of its jobs resolved to remote_global with
        is_global_remote=True -- a factual claim that the job is open to
        everyone, made purely because the parser could not read the script.
        """
        session = MagicMock()
        calls: list[str] = []
        params_seen: list[dict] = []

        def _execute(stmt, params=None):  # noqa: C901 - a fake DB router
            sql = " ".join(str(stmt).split())
            calls.append(sql)
            if isinstance(params, dict):
                params_seen.append(dict(params))
            if sql.startswith("SELECT location_id FROM core.location_aliases"):
                return _scalar_result(None)
            if "FROM ref.sources" in sql:
                return _scalar_result("jobvision")
            if "FROM ref.cities" in sql:
                return _rows_result([])
            if "FROM ref.regions" in sql:
                return _rows_result([])
            if "FROM ref.countries" in sql:
                # Distinguish the two country queries. source_home_country
                # filters with "iso_code_2 = :iso"; _match_country matches
                # country_name OR iso_code_2 OR iso_code_3 against a single
                # :code value. "Narnia" must match no country by name, so only
                # the home-country lookup may return a row here.
                if ":iso" in sql:
                    return _scalar_result(706)  # Iran
                return _scalar_result(None)
            if "FROM ref.remote_work_types" in sql:
                return _scalar_result(3)  # remote_country
            if sql.startswith("SELECT location_id FROM ref.locations"):
                return _scalar_result(None)
            if sql.startswith("INSERT INTO ref.locations"):
                return _scalar_result(777)
            if sql.startswith("INSERT INTO core.location_aliases"):
                return MagicMock()
            raise AssertionError(f"unexpected SQL: {sql}")

        session.execute.side_effect = _execute

        location_id = resolve_and_cache_location(session, "Narnia", source_id=2)

        assert location_id == 777
        # The INSERT uses bind params, so assert on the bound values: the
        # country must be Iran's id and the row must NOT claim global remote.
        insert_params = next(p for p in params_seen if "is_global_remote" in p)
        assert insert_params["country_id"] == 706
        assert insert_params["is_global_remote"] is False
        assert insert_params["remote_work_type_id"] == 3  # remote_country


@pytest.mark.parametrize(
    "resolved_kwargs",
    [
        {
            "city_id": 1,
            "region_id": 2,
            "country_id": 3,
            "remote_work_type_code": "remote_city",
            "is_global_remote": False,
            "match_method": "city_exact",
        },
        {
            "city_id": None,
            "region_id": None,
            "country_id": None,
            "remote_work_type_code": "remote_global",
            "is_global_remote": True,
            "match_method": "global_assertion",
        },
    ],
)
def test_resolved_location_is_a_frozen_dataclass(resolved_kwargs: dict) -> None:
    # Trivial construction/shape guard -- catches an accidental field
    # rename in ResolvedLocation breaking every caller silently.
    resolved = ResolvedLocation(**resolved_kwargs)
    assert resolved.match_method == resolved_kwargs["match_method"]

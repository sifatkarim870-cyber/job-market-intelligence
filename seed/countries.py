"""
Seeds ref.countries (ISO 3166-1). Initial set: ~65 countries covering every
major remote-hiring market plus regional coverage across all continents.
`default_currency_id` is resolved from the currencies just seeded via
base.get_id_map — this module MUST run after currencies.py.
"""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, get_id_map, upsert_many

# (iso2, iso3, name, continent, default_currency_iso)
_COUNTRIES_RAW: list[tuple[str, str, str, str, str | None]] = [
    ("US", "USA", "United States", "North America", "USD"),
    ("CA", "CAN", "Canada", "North America", "CAD"),
    ("MX", "MEX", "Mexico", "North America", "MXN"),
    ("GB", "GBR", "United Kingdom", "Europe", "GBP"),
    ("IE", "IRL", "Ireland", "Europe", "EUR"),
    ("DE", "DEU", "Germany", "Europe", "EUR"),
    ("FR", "FRA", "France", "Europe", "EUR"),
    ("ES", "ESP", "Spain", "Europe", "EUR"),
    ("PT", "PRT", "Portugal", "Europe", "EUR"),
    ("IT", "ITA", "Italy", "Europe", "EUR"),
    ("NL", "NLD", "Netherlands", "Europe", "EUR"),
    ("BE", "BEL", "Belgium", "Europe", "EUR"),
    ("CH", "CHE", "Switzerland", "Europe", "CHF"),
    ("AT", "AUT", "Austria", "Europe", "EUR"),
    ("SE", "SWE", "Sweden", "Europe", "SEK"),
    ("NO", "NOR", "Norway", "Europe", "NOK"),
    ("DK", "DNK", "Denmark", "Europe", "DKK"),
    ("FI", "FIN", "Finland", "Europe", "EUR"),
    ("PL", "POL", "Poland", "Europe", "PLN"),
    ("CZ", "CZE", "Czechia", "Europe", "CZK"),
    ("HU", "HUN", "Hungary", "Europe", "HUF"),
    ("RO", "ROU", "Romania", "Europe", "RON"),
    ("GR", "GRC", "Greece", "Europe", "EUR"),
    ("UA", "UKR", "Ukraine", "Europe", "UAH"),
    ("TR", "TUR", "Turkey", "Europe", "TRY"),
    ("RU", "RUS", "Russia", "Europe", None),
    ("IN", "IND", "India", "Asia", "INR"),
    ("CN", "CHN", "China", "Asia", "CNY"),
    ("JP", "JPN", "Japan", "Asia", "JPY"),
    ("KR", "KOR", "South Korea", "Asia", "KRW"),
    ("SG", "SGP", "Singapore", "Asia", "SGD"),
    ("HK", "HKG", "Hong Kong", "Asia", "HKD"),
    ("PH", "PHL", "Philippines", "Asia", "PHP"),
    ("ID", "IDN", "Indonesia", "Asia", "IDR"),
    ("MY", "MYS", "Malaysia", "Asia", "MYR"),
    ("TH", "THA", "Thailand", "Asia", "THB"),
    ("VN", "VNM", "Vietnam", "Asia", "VND"),
    ("PK", "PAK", "Pakistan", "Asia", "PKR"),
    ("BD", "BGD", "Bangladesh", "Asia", "BDT"),
    ("IL", "ISR", "Israel", "Asia", "ILS"),
    ("AE", "ARE", "United Arab Emirates", "Asia", "AED"),
    ("SA", "SAU", "Saudi Arabia", "Asia", "SAR"),
    # Added for Job.am (Armenia, onboarding 2026-10-05): the board's
    # ~1,100 listings are overwhelmingly Armenian cities, and without a
    # ref.countries row every one of them fell through to the shared
    # "unmatched" location (is_global_remote=true) — see seed/cities.py's
    # Armenian entries for the city half of the same fix.
    ("AM", "ARM", "Armenia", "Asia", "AMD"),
    # Iran was missing, and jobvision (60,982 rows, 58% of the corpus) plus
    # jobinja (16,529) are both Iranian -- every one of their postings fell
    # through to the "unresolved -> remote_global" fallback purely because the
    # country had no row to match. No currency is assigned: IRR is not freely
    # convertible and the seed has no IRR row, so NULL is the honest value.
    ("IR", "IRN", "Iran", "Asia", None),
    # Mauritius backs app.myjob.mu (source code "myjob", 410 rows), which had
    # the same fallback problem.
    ("MU", "MUS", "Mauritius", "Africa", "MUR"),
    ("AU", "AUS", "Australia", "Oceania", "AUD"),
    ("NZ", "NZL", "New Zealand", "Oceania", "NZD"),
    ("ZA", "ZAF", "South Africa", "Africa", "ZAR"),
    ("NG", "NGA", "Nigeria", "Africa", "NGN"),
    ("KE", "KEN", "Kenya", "Africa", "KES"),
    ("EG", "EGY", "Egypt", "Africa", "EGP"),
    ("GH", "GHA", "Ghana", "Africa", None),
    ("BR", "BRA", "Brazil", "South America", "BRL"),
    ("AR", "ARG", "Argentina", "South America", "ARS"),
    ("CL", "CHL", "Chile", "South America", "CLP"),
    ("CO", "COL", "Colombia", "South America", "COP"),
    ("PE", "PER", "Peru", "South America", None),
    ("UY", "URY", "Uruguay", "South America", None),
]


def seed_countries(conn: Connection) -> SeedResult:
    currency_ids = get_id_map(
        conn, schema="ref", table_name="currencies", key_col="iso_code", id_col="currency_id"
    )
    rows = [
        {
            "iso_code_2": iso2,
            "iso_code_3": iso3,
            "country_name": name,
            "continent": continent,
            "default_currency_id": currency_ids.get(cur_iso) if cur_iso else None,
        }
        for iso2, iso3, name, continent, cur_iso in _COUNTRIES_RAW
    ]
    return upsert_many(
        conn,
        schema="ref",
        table_name="countries",
        rows=rows,
        conflict_cols=("iso_code_2",),
    )

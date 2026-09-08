"""
Seeds ref.regions. No global standard exists for subdivisions, so this
seeds only the countries where postings will realistically need
state/province-level resolution in year one (US, Canada, India, Australia,
UK). Expand per-country as new markets are prioritized — this is additive,
never breaking.
"""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, get_id_map, upsert_many

_US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
]

_CA_PROVINCES = [
    "Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba",
    "Saskatchewan", "Nova Scotia", "New Brunswick",
    "Newfoundland and Labrador", "Prince Edward Island",
]

_IN_STATES = [
    "Maharashtra", "Karnataka", "Delhi", "Tamil Nadu", "Telangana",
    "Uttar Pradesh", "West Bengal", "Gujarat", "Haryana", "Punjab",
]

_AU_STATES = [
    "New South Wales", "Victoria", "Queensland", "Western Australia",
    "South Australia", "Tasmania", "Australian Capital Territory",
]

_GB_REGIONS = [
    "England", "Scotland", "Wales", "Northern Ireland",
]

_BY_COUNTRY: dict[str, list[str]] = {
    "US": _US_STATES,
    "CA": _CA_PROVINCES,
    "IN": _IN_STATES,
    "AU": _AU_STATES,
    "GB": _GB_REGIONS,
}


def seed_regions(conn: Connection) -> SeedResult:
    country_ids = get_id_map(
        conn, schema="ref", table_name="countries", key_col="iso_code_2", id_col="country_id"
    )
    rows = []
    for iso2, names in _BY_COUNTRY.items():
        country_id = country_ids[iso2]
        for name in names:
            rows.append({"country_id": country_id, "region_name": name, "region_code": None})

    return upsert_many(
        conn,
        schema="ref",
        table_name="regions",
        rows=rows,
        conflict_cols=("country_id", "region_name"),
    )

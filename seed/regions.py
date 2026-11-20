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
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
    "District of Columbia",
]

_CA_PROVINCES = [
    "Ontario",
    "Quebec",
    "British Columbia",
    "Alberta",
    "Manitoba",
    "Saskatchewan",
    "Nova Scotia",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Prince Edward Island",
]

_IN_STATES = [
    "Maharashtra",
    "Karnataka",
    "Delhi",
    "Tamil Nadu",
    "Telangana",
    "Uttar Pradesh",
    "West Bengal",
    "Gujarat",
    "Haryana",
    "Punjab",
]

_AU_STATES = [
    "New South Wales",
    "Victoria",
    "Queensland",
    "Western Australia",
    "South Australia",
    "Tasmania",
    "Australian Capital Territory",
]

_GB_REGIONS = [
    "England",
    "Scotland",
    "Wales",
    "Northern Ireland",
]

_BR_STATES = [
    # 26 states + the federal district. Seeded because vagas.com.br and
    # greenhouse carry Brazilian postings whose ``addressRegion`` is a bare
    # state abbreviation ("SC", "PA", "MG"), and with zero Brazilian regions
    # seeded there was nothing correct for such a token to match -- which is how
    # 'Governador Celso Ramos, SC' (Santa Catarina) reached US "South Carolina".
    "Acre",
    "Alagoas",
    "Amapa",
    "Amazonas",
    "Bahia",
    "Ceara",
    "Distrito Federal",
    "Espirito Santo",
    "Goias",
    "Maranhao",
    "Mato Grosso",
    "Mato Grosso do Sul",
    "Minas Gerais",
    "Para",
    "Paraiba",
    "Parana",
    "Pernambuco",
    "Piaui",
    "Rio de Janeiro",
    "Rio Grande do Norte",
    "Rio Grande do Sul",
    "Rondonia",
    "Roraima",
    "Santa Catarina",
    "Sao Paulo",
    "Sergipe",
    "Tocantins",
]

_AF_PROVINCES = [
    # Afghanistan, from acbar.org (112 rows) and jobs.af (12 rows). Every
    # measured posting names its province in the board's own Location field, e.g.
    # "Baghlan - Pull-e-Khumri" and "Nangarhar - Chaprahar, Khogyani".
    "Badakhshan",
    "Badghis",
    "Baghlan",
    "Balkh",
    "Bamyan",
    "Daikundi",
    "Faryab",
    "Ghazni",
    "Ghor",
    "Helmand",
    "Herat",
    "Jowzjan",
    "Kabul",
    "Kandahar",
    "Kapisa",
    "Khost",
    "Kunar",
    "Laghman",
    "Logar",
    "Nangarhar",
    "Nimruz",
    "Nuristan",
    "Paktia",
    "Paktika",
    "Parwan",
    "Samangan",
    "Sar-e Pul",
    "Takhar",
    "Uruzgan",
    "Wardak",
    "Zabul",
]

_AO_PROVINCES = [
    # Angola, from angolaemprego.com. Postings name the province directly
    # ("Luanda Province").
    "Bengo",
    "Bie",
    "Benguela",
    "Bié",
    "Cabinda",
    "Cuando Cubango",
    "Cuanza Norte",
    "Cuanza Sul",
    "Huambo",
    "Huíla",
    "Luanda",
    "Lunda Norte",
    "Lunda Sul",
    "Malanje",
    "Moxico",
    "Namibe",
    "Uíge",
    "Zaire",
]

_RW_DISTRICTS = [
    # Rwanda's five former provinces.
    "Butare",
    "Byumba",
    "Gitarama",
    "Kibuye",
    "Kigali",
    "Ruhengeri",
]

_GH_REGIONS = [
    # Ghana's 16 regions, from jobwebghana.com (65 rows).
    "Ahafo",
    "Ashanti",
    "Bono",
    "Central",
    "Eastern",
    "Greater Accra",
    "Northern",
    "Oti",
    "Savannah",
    "Upper East",
    "Upper West",
    "Volta",
    "Western",
    "Western North",
    "North East",
    "Bono East",
]

_ZA_PROVINCES = [
    # South Africa, from careers24 (40 rows) and careerjunction (23).
    "Eastern Cape",
    "Free State",
    "Gauteng",
    "KwaZulu-Natal",
    "Limpopo",
    "Mpumalanga",
    "Northern Cape",
    "North West",
    "Western Cape",
]

_PT_REGIONS = [
    # Portugal, from net_empregos (30 rows) and greenhouse (30).
    "Lisboa",
    "Porto",
    "Braga",
    "Coimbra",
    "Faro",
    "Aveiro",
    "Setubal",
]

_ES_PROVINCES = [
    # Spain's 50 provinces plus the autonomous cities of Ceuta and Melilla, for
    # Empléate (empleate_es). The list is the portal's own ``provinciaF`` facet:
    # exactly 52 distinct values were measured across all 26,073 visible ads on
    # 2026-11-20, and the parser emits that value verbatim as the middle
    # segment of "<ciudadF>; <provinciaF>; ES". Because ``_match_region`` is an
    # exact case-insensitive match on ``region_name`` and never normalizes the
    # seeded side, the spellings below must stay byte-identical to the source's
    # (hence uppercase "A CORUÑA", "ILLES BALEARS", and the abbreviated
    # "STA.CRUZ DE TENERIFE") rather than prettified.
    "BARCELONA",
    "MADRID",
    "VALENCIA",
    "VIZCAYA",
    "ALICANTE",
    "ASTURIAS",
    "GIRONA",
    "TARRAGONA",
    "ZARAGOZA",
    "MURCIA",
    "GUIPUZCOA",
    "MALAGA",
    "LLEIDA",
    "LEON",
    "SEVILLA",
    "LAS PALMAS",
    "ALAVA",
    "CASTELLON",
    "A CORUÑA",
    "ILLES BALEARS",
    "BURGOS",
    "BADAJOZ",
    "STA.CRUZ DE TENERIFE",
    "PONTEVEDRA",
    "ZAMORA",
    "TOLEDO",
    "NAVARRA",
    "VALLADOLID",
    "HUESCA",
    "LA RIOJA",
    "CANTABRIA",
    "GRANADA",
    "CACERES",
    "ALMERIA",
    "CORDOBA",
    "CADIZ",
    "JAEN",
    "ALBACETE",
    "LUGO",
    "GUADALAJARA",
    "PALENCIA",
    "HUELVA",
    "SALAMANCA",
    "OURENSE",
    "SEGOVIA",
    "TERUEL",
    "SORIA",
    "CIUDAD REAL",
    "CUENCA",
    "AVILA",
    "CEUTA",
    "MELILLA",
]

_MY_REGIONS = [
    # Malaysia's 13 states plus 3 federal territories, from hiredly (30 rows,
    # of which 29 read "Petaling Jaya, Selangor"). Before this, ref.regions had
    # no Malaysian row at all, so every one of those postings resolved to
    # country-only with the state sitting in the raw text.
    "Johor",
    "Kedah",
    "Kelantan",
    "Melaka",
    "Negeri Sembilan",
    "Pahang",
    "Perak",
    "Perlis",
    "Pulau Pinang",
    "Sabah",
    "Sarawak",
    "Selangor",
    "Terengganu",
    "Kuala Lumpur",
    "Labuan",
    "Putrajaya",
]

#: Ireland's 26 traditional counties, for jobsireland.ie.
#:
#: Every address on that board is "<premises>, <town>, Co. <County>, <Eircode>",
#: so without these the county segment matches nothing and every row resolves to
#: country-only. All 26 were observed across 600 live cards. Seeded WITHOUT the
#: "Co." prefix because ``_normalize_segment`` now strips it -- that way both
#: "Co. Mayo" and a bare "Mayo" resolve.
_IE_COUNTIES = [
    "Carlow",
    "Cavan",
    "Clare",
    "Cork",
    "Donegal",
    "Dublin",
    "Galway",
    "Kerry",
    "Kildare",
    "Kilkenny",
    "Laois",
    "Leitrim",
    "Limerick",
    "Longford",
    "Louth",
    "Mayo",
    "Meath",
    "Monaghan",
    "Offaly",
    "Roscommon",
    "Sligo",
    "Tipperary",
    "Waterford",
    "Westmeath",
    "Wexford",
    "Wicklow",
]

#: Egypt's 27 governorates, for forasna.
#:
#: The board's own spelling, without the hamza on the "al-" article, so a
#: posting's region string matches what the site publishes. 17 of the 27 were
#: observed on live postings (2026-10-20); the rest are the remaining
#: governorates.
#:
#: Seeded because forasna writes every address as
#: "<locality>, <governorate>" and the corpus resolves the region from the
#: second half. Without them every Egyptian posting would land country-only.
_EG_GOVERNORATES = [
    "القاهرة",
    "الجيزة",
    "الاسكندرية",
    "الدقهلية",
    "الشرقية",
    "المنوفية",
    "المنيا",
    "القليوبية",
    "الغربية",
    "البحيرة",
    "كفر الشيخ",
    "بني سويف",
    "الفيوم",
    "أسيوط",
    "سوهاج",
    "قنا",
    "الأقصر",
    "أسوان",
    "البحر الأحمر",
    "الوادي الجديد",
    "مطروح",
    "شمال سيناء",
    "جنوب سيناء",
    "بورسعيد",
    "دمياط",
    "السويس",
    "الاسماعيلية",
]

#: Saudi regions seen on forasna, for the postings whose addressCountry is SA.
#:
#: Without them, a Saudi posting's locality would either match an Egyptian city
#: of the same name or fall through to the source's home country -- and
#: "الرياض" IS both a village in Kafr El Sheikh and Riyadh, so the name
#: collides. The region is what tells them apart.
_SA_REGIONS = [
    "الرياض",
    "أبها",
    "تبوك",
]

#: Chile's 16 regions, for chiletrabajos.cl.
#:
#: The board's ``JobPosting.jobLocation.address.addressRegion`` is the
#: **ISO 3166-2:CL code** (``AT`` Atacama, ``AN`` Antofagasta, ``LL`` Los
#: Lagos, ``LI`` O'Higgins, ``RM`` Metropolitana, ``BI`` Biobío measured),
#: not a name. The parser maps the code onto these names, and the resolver
#: matches ``region_name`` exactly, so this table and
#: ``scrapers/chiletrabajos_cl/parser.py::_REGION_BY_CODE`` must stay
#: byte-identical. ``region_code`` records the official ``CL-XX`` code.
_CL_REGIONS = [
    "Arica y Parinacota",
    "Tarapacá",
    "Antofagasta",
    "Atacama",
    "Coquimbo",
    "Valparaíso",
    "Metropolitana de Santiago",
    "O'Higgins",
    "Maule",
    "Ñuble",
    "Biobío",
    "La Araucanía",
    "Los Ríos",
    "Los Lagos",
    "Aysén",
    "Magallanes",
]

_CL_REGION_CODES = {
    "Arica y Parinacota": "CL-AP",
    "Tarapacá": "CL-TA",
    "Antofagasta": "CL-AN",
    "Atacama": "CL-AT",
    "Coquimbo": "CL-CO",
    "Valparaíso": "CL-VS",
    "Metropolitana de Santiago": "CL-RM",
    "O'Higgins": "CL-LI",
    "Maule": "CL-ML",
    "Ñuble": "CL-NB",
    "Biobío": "CL-BI",
    "La Araucanía": "CL-AR",
    "Los Ríos": "CL-LR",
    "Los Lagos": "CL-LL",
    "Aysén": "CL-AI",
    "Magallanes": "CL-MA",
}


_BY_COUNTRY: dict[str, list[str]] = {
    "US": _US_STATES,
    "CA": _CA_PROVINCES,
    "IN": _IN_STATES,
    "AU": _AU_STATES,
    "GB": _GB_REGIONS,
    "BR": _BR_STATES,
    "AF": _AF_PROVINCES,
    "AO": _AO_PROVINCES,
    "RW": _RW_DISTRICTS,
    "GH": _GH_REGIONS,
    "ZA": _ZA_PROVINCES,
    "PT": _PT_REGIONS,
    "ES": _ES_PROVINCES,
    "MY": _MY_REGIONS,
    "IE": _IE_COUNTIES,
    "EG": _EG_GOVERNORATES,
    "SA": _SA_REGIONS,
    "CL": _CL_REGIONS,
}


def seed_regions(conn: Connection) -> SeedResult:
    country_ids = get_id_map(
        conn, schema="ref", table_name="countries", key_col="iso_code_2", id_col="country_id"
    )
    rows = []
    for iso2, names in _BY_COUNTRY.items():
        country_id = country_ids[iso2]
        codes = _CL_REGION_CODES if iso2 == "CL" else {}
        for name in names:
            rows.append(
                {
                    "country_id": country_id,
                    "region_name": name,
                    "region_code": codes.get(name),
                }
            )

    return upsert_many(
        conn,
        schema="ref",
        table_name="regions",
        rows=rows,
        conflict_cols=("country_id", "region_name"),
    )

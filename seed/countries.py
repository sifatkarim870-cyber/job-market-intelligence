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
    # Added for the alfred source. Without this row the resolver cannot place a
    # single Icelandic posting: it would leave country_id NULL on every row and
    # fall back to the global-remote location, which is exactly the failure the
    # other single-country sources were added to fix.
    ("IS", "ISL", "Iceland", "Europe", "ISK"),
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
    ("AZ", "AZE", "Azerbaijan", "Asia", "AZN"),
    ("SO", "SOM", "Somalia", "Africa", "SOS"),
    # Added for Emploitic (Algeria). The resolver's SOURCE_HOME_COUNTRY map
    # said FR for years; the board is Algerian, and DZD is already seeded.
    ("DZ", "DZA", "Algeria", "Africa", "DZD"),
    ("NP", "NPL", "Nepal", "Asia", "NPR"),
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
    # Angola backs angolaemprego.com (source code "angola_emprego", 20 rows).
    # Added because its addressCountry is not consistently present on the
    # postings, so SOURCE_HOME_COUNTRY's "AO" fallback had nothing to resolve
    # against and every one of those rows collapsed onto the global-remote
    # location instead of Angola. A fallback pointing at a country the seed
    # does not contain is silently a no-op, which is what happened.
    ("AO", "AGO", "Angola", "Africa", "AOA"),
    # Rwanda backs jobinrwanda.com (source code "jobinrwanda"). It publishes
    # no location field at all, so SOURCE_HOME_COUNTRY's "RW" is the only
    # thing that can give those rows a country -- and a fallback aimed at a
    # country the seed lacks is silently a no-op, which is what Angola was.
    ("RW", "RWA", "Rwanda", "Africa", "RWF"),
    ("FJ", "FJI", "Fiji", "Oceania", "FJD"),
    # Afghanistan backs acbar.org. A fallback aimed at a country the seed
    # lacks is silently a no-op, which is what Angola was.
    ("AF", "AFG", "Afghanistan", "Asia", "AFN"),
    ("NG", "NGA", "Nigeria", "Africa", "NGN"),
    ("KE", "KEN", "Kenya", "Africa", "KES"),
    # Uganda backs brightermonday.co.ug (source code "brightermonday_co_ug"). The
    # board's JSON-LD carries addressCountry "UG" and usually only the city
    # ("Kampala"), so the SOURCE_HOME_COUNTRY fallback needs a row here to
    # resolve against; a fallback aimed at a country the seed lacks is silently
    # a no-op.
    ("UG", "UGA", "Uganda", "Africa", "UGX"),
    ("EG", "EGY", "Egypt", "Africa", "EGP"),
    ("GH", "GHA", "Ghana", "Africa", None),
    ("BR", "BRA", "Brazil", "South America", "BRL"),
    ("AR", "ARG", "Argentina", "South America", "ARS"),
    ("CL", "CHL", "Chile", "South America", "CLP"),
    ("CO", "COL", "Colombia", "South America", "COP"),
    ("PE", "PER", "Peru", "South America", None),
    ("UY", "URY", "Uruguay", "South America", None),
    # Tunisia backs tanitjobs.com (source code "tanitjobs"). Africa previously
    # held only DZ/EG/KE/NG, and a SOURCE_HOME_COUNTRY fallback pointing at a
    # country the seed lacks is silently a no-op -- the same failure Angola and
    # Rwanda were added to fix -- so TN must be seeded for the fallback to land.
    ("TN", "TUN", "Tunisia", "Africa", "TND"),
    # El Salvador backs tecoloco.com.sv (source code "sv_tecoloco_com"). Its
    # postings name the country as 'El Salvador' rather than the ISO code and
    # often carry only a department ("La Libertad"), so the SOURCE_HOME_COUNTRY
    # fallback needs a row here to resolve against; a fallback aimed at a
    # country the seed lacks is silently a no-op (the Angola/Rwanda failure).
    ("SV", "SLV", "El Salvador", "North America", "USD"),
    # North Macedonia backs kariera.mk (source code "kariera_mk"). The board's
    # detail pages name the city only ("Скопје"), never the country, so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op.
    ("MK", "MKD", "North Macedonia", "Europe", "MKD"),
    # Guatemala backs tecoloco.com.gt (source code "gt_tecoloco_com"). Its
    # postings name the country 'Guatemala' (not the ISO code) and often carry
    # only a department/city, so the SOURCE_HOME_COUNTRY fallback needs a row
    # here to resolve against.
    ("GT", "GTM", "Guatemala", "North America", "GTQ"),
    # Nicaragua and Honduras back the tecoloco.com.ni / tecoloco.com.hn
    # siblings (source codes "ni_tecoloco_com" / "hn_tecoloco_com"); their
    # JSON-LD addressCountry is the NAME ('Nicaragua' / 'Honduras'), so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against.
    ("NI", "NIC", "Nicaragua", "North America", "NIO"),
    ("HN", "HND", "Honduras", "North America", "HNL"),
    # Côte d'Ivoire backs emploi.educarriere.ci (source code "ci_educarriere").
    # Its JSON-LD addressCountry is the ISO code "CI" and the addressLocality is
    # often just the country or a bare city ("Abidjan"), so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op.
    ("CI", "CIV", "Côte d'Ivoire", "Africa", "XOF"),
    # Moldova backs rabota.md (source code "rabota_md"). Its postings name the
    # city ("Chișinău") and the JSON-LD addressCountry code "MD", but the
    # SOURCE_HOME_COUNTRY fallback still needs a row here to resolve against for
    # rows whose locality is a district or abroad; a fallback aimed at a country
    # the seed lacks is silently a no-op.
    ("MD", "MDA", "Moldova", "Europe", "MDL"),
    # Belarus backs rabota.by (source code "rabota_by"). Its postings name the
    # city ("Минск") and the JSON-LD addressCountry code "BY", but the
    # SOURCE_HOME_COUNTRY fallback still needs a row here to resolve against for
    # rows whose locality is a district or abroad; a fallback aimed at a country
    # the seed lacks is silently a no-op.
    ("BY", "BLR", "Belarus", "Europe", "BYN"),
    # Lithuania backs cvbankas.lt (source code "cvbankas_lt"). Its detail pages
    # name only the city ("Vilnius"/"Kaunas"/"Panevėžys") and carry no country,
    # so the SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op. (The older
    # cv.lt source points at the same country and had the same silent no-op, so
    # its rows gain a country on their next run too.)
    ("LT", "LTU", "Lithuania", "Europe", "EUR"),
    # Morocco backs rekrute.com (source code "rekrute_com"). Its JSON-LD
    # addressCountry is the country name "Maroc", not an ISO code, and the
    # locality is a bare city ("Casablanca"/"Rabat"), so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op -- which is
    # exactly what left this source's earlier rows country-less.
    ("MA", "MAR", "Morocco", "Africa", "MAD"),
    # Montenegro backs zaposli.me (source code "zaposli_me"). Its detail pages
    # name the locality as "Podgorica, Crna Gora" (city + country name) and
    # carry no ISO country code, so the SOURCE_HOME_COUNTRY fallback needs a row
    # here to resolve against; a fallback aimed at a country the seed lacks is
    # silently a no-op.
    ("ME", "MNE", "Montenegro", "Europe", "EUR"),
    # Myanmar backs myjobs.com.mm (source code "myjobs_mm"). Its JSON-LD
    # addressCountry is the name "Myanmar" and the locality is a township
    # ("Yankin Township", "Mayangon Township"), so both the cleaner's name
    # normalization and the SOURCE_HOME_COUNTRY fallback need a row here; a
    # fallback aimed at a country the seed lacks is silently a no-op.
    ("MM", "MMR", "Myanmar", "Asia", "MMK"),
    # Kazakhstan backs hh.kz (source code "hh_kz"). The board's JSON-LD
    # addressCountry is the ISO code "KZ" and the locality is Cyrillic
    # ("Астана", "Алматы"), which does not resolve against ref.cities, so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op.
    ("KZ", "KAZ", "Kazakhstan", "Asia", "KZT"),
    # Uzbekistan backs hh.uz (source code "hh_uz"), the same HeadHunter platform
    # as its Kazakh sibling. The JSON-LD addressCountry is the ISO code "UZ" and
    # the locality is Cyrillic ("Ташкент"), which does not resolve against
    # ref.cities, so the SOURCE_HOME_COUNTRY fallback needs a row here to
    # resolve against; a fallback aimed at a country the seed lacks is silently
    # a no-op.
    ("UZ", "UZB", "Uzbekistan", "Asia", "UZS"),
    # Panama backs konzerta_pa (source code "konzerta_pa"), the same Navent
    # platform as the already-built zonajobs_com_ar. The API's location detail
    # is the name "Panamá, Panamá, Panama" and carries no ISO code, so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op.
    ("PA", "PAN", "Panama", "North America", "PAB"),
    # Ecuador backs multitrabajos_ec (source code "multitrabajos_ec"), the same
    # Navent platform as konzerta_pa/zonajobs_com_ar. The API's location detail
    # is the name "Quito, Pichincha, Ecuador" and carries no ISO code, so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op. Ecuador
    # is dollarized, so its default currency is USD (already seeded).
    ("EC", "ECU", "Ecuador", "South America", "USD"),
    # Venezuela backs bumeran_ve (source code "bumeran_ve"), the same Navent
    # platform as konzerta_pa/zonajobs_com_ar. The API's location detail is the
    # name "El Tigre, Anzoátegui, Venezuela" and carries no ISO code, so the
    # SOURCE_HOME_COUNTRY fallback needs a row here to resolve against; a
    # fallback aimed at a country the seed lacks is silently a no-op.
    ("VE", "VEN", "Venezuela", "South America", "VES"),
    # Cyprus backs ergodotisi_cy (source code "ergodotisi_cy"). The board's
    # JSON-LD addressCountry is the name "Cyprus" and its locality is a bare
    # city ("Nicosia"), so the SOURCE_HOME_COUNTRY fallback needs a row here to
    # resolve against; a fallback aimed at a country the seed lacks is silently
    # a no-op.
    ("CY", "CYP", "Cyprus", "Europe", "EUR"),
    # Trinidad and Tobago backs trinidadjob_tt (source code "trinidadjob_tt").
    # The board publishes no ISO code and its JSON-LD jobLocation.address is a
    # bare list of localities ("Port of Spain/ St James/ Morvant"), so the
    # SOURCE_HOME_COUNTRY fallback needs this row to resolve; a fallback aimed
    # at a country the seed lacks is silently a no-op.
    ("TT", "TTO", "Trinidad and Tobago", "North America", "TTD"),
    # Malawi backs jobsearchmalawi_com (source code "jobsearchmalawi_com"). The
    # board's JSON-LD jobLocation.address is a bare locality ("Lilongwe",
    # "Mangochi") with no country, so the SOURCE_HOME_COUNTRY fallback needs
    # this row to resolve; the disabled mwnation_com source named Malawi too but
    # no ref.countries row ever existed.
    ("MW", "MWI", "Malawi", "Africa", "MWK"),
    # Jordan backs bayt_com_jo (source code "bayt_com_jo"). Bayt's JSON-LD
    # addressCountry is the code "JO", but no ref.countries row existed, so the
    # akhtaboot_com source's few Jordan rows never attributed either. A
    # SOURCE_HOME_COUNTRY fallback aimed at a country the seed lacks is silently
    # a no-op, so this row is required.
    ("JO", "JOR", "Jordan", "Asia", "JOD"),
    # Qatar backs bayt_com_qa (source code "bayt_com_qa"). The qatarliving_com
    # source named Qatar but its rows were almost all "Worldwide / remote", so
    # no ref.countries row was ever needed; Bayt's Qatar ads carry real Doha
    # localities and the ISO code "QA", and a SOURCE_HOME_COUNTRY fallback aimed
    # at a country the seed lacks is silently a no-op, so this row is required.
    ("QA", "QAT", "Qatar", "Asia", "QAR"),
    # Kuwait backs gulftalent_kw (source code "gulftalent_kw"). GulfTalent's
    # Kuwait ads carry the country name "Kuwait" and the locality "Kuwait City",
    # but no ref.countries row existed, so no Kuwaiti posting could attribute; a
    # SOURCE_HOME_COUNTRY fallback aimed at a country the seed lacks is silently
    # a no-op, so this row is required.
    ("KW", "KWT", "Kuwait", "Asia", "KWD"),
    # Latvia backs ss_lv (source code "ss_lv"). SS.lv is the country's large
    # classifieds board and its work ads carry no ISO code -- the resolver sees
    # Latvian locality strings ("Rīga, centrs") only -- so the
    # SOURCE_HOME_COUNTRY fallback needs this row to resolve; a fallback aimed
    # at a country the seed lacks is silently a no-op.
    ("LV", "LVA", "Latvia", "Europe", "EUR"),
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

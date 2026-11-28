"""Unit tests for the UWV Werk.nl (Netherlands) scraper.

No network and no database: every test drives the pure mapping helpers or a
synthetic list-item + detail pair built from the shapes measured on
2026-11-28. The fixtures are constructed here, not copied from a live
response, so the tests describe the contract rather than one capture.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from job_market_intel.scrapers.werk_nl import WerkNlClient, WerkNlSettings
from job_market_intel.scrapers.werk_nl.exceptions import WerkNlParseError
from job_market_intel.scrapers.werk_nl.models import RawWerkNlJob
from job_market_intel.scrapers.werk_nl.parser import (
    WerkNlParser,
    build_location,
    map_employment_type,
    normalize_description,
    parse_amount,
    parse_date,
    parse_salary_indication,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3000", 3000.0),
        ("3.000", 3000.0),
        ("3.400,00", 3400.0),
        ("15,50", 15.5),
        ("1.570.000", 1570000.0),
        ("0", None),
        ("", None),
        ("—", None),
    ],
)
def test_parse_amount(raw: str, expected: float | None) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, (None, None, "monthly", False)),
        ("", (None, None, "monthly", False)),
        ("5000", (5000.0, None, "monthly", True)),
        ("€ 3.000 - € 4.000 per maand", (3000.0, 4000.0, "monthly", True)),
        ("€ 15,50 per uur", (15.5, None, "hourly", True)),
        ("€ 45.000 per jaar", (45000.0, None, "yearly", True)),
    ],
)
def test_parse_salary_indication(
    raw: object, expected: tuple[float | None, float | None, str, bool]
) -> None:
    assert parse_salary_indication(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-29T00:00:00", datetime(2026, 10, 29)),
        ("2026-11-28 00:00:00", datetime(2026, 11, 28)),
        ("2026-12-28", datetime(2026, 12, 28)),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(raw: object, expected: datetime | None) -> None:
    assert parse_date(raw) == expected


def test_normalize_description_strips_html_and_entities() -> None:
    raw = "Wij zoeken &quot;verpleegkundigen&quot;.\r\n\r\n<p>Ervaring: 3 jaar</p>"
    text = normalize_description(raw)
    assert '"verpleegkundigen"' in text
    assert "Ervaring: 3 jaar" in text
    assert "<p>" not in text
    assert "\r" not in text
    assert normalize_description(None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tijdelijk", "temporary"),
        ("tijdelijk", "temporary"),
        ("Vast", None),
        ("Mogelijk vast", None),
        ("", None),
        (None, None),
    ],
)
def test_map_employment_type(raw: object, expected: str | None) -> None:
    assert map_employment_type(raw) == expected


def test_build_location_composes_city_and_country() -> None:
    assert build_location({"city": "AMSTELVEEN", "country": "NL"}) == "AMSTELVEEN; NL"
    assert build_location({"city": "", "country": "NL"}) == "NL"
    assert build_location({"city": "Antwerpen", "country": "BE"}) == "Antwerpen; BE"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Word verpleegkundige op onze dynamische verloskundeafdeling, waar geen dag "
    "hetzelfde is!\n\nInformatie\nWelkom bij de verloskunde afdeling.\n\n"
    "De functie\nAls verpleegkundige bied je laag- en middencomplexe zorg aan "
    "moeder en kind.\n\nJouw team\nJe werkt samen met een enthousiast team."
)


def _list_item(**overrides: object) -> dict:
    item: dict = {
        "key": "2001:L:72002335",
        "referenceNumber": 72002335,
        "score": 100,
        "resultDepth": 0,
        "internalReferenceNumber": None,
        "profession": "Verpleegkundige",
        "vacatureTitle": "Verpleegkundige Verloskunde",
        "modified": "2026-11-28 00:00:00",
        "organisation": "Ziekenhuis Amstelland",
        "workLocationCity": "AMSTELVEEN",
        "workLocationType": "Vaste werklocatie",
        "workLocationForeignCountry": None,
        "workLocationForeignCity": None,
        "minHours": 36,
        "maxHours": 40,
        "contractType": "Vast",
        "studyLevel": "Niet opgegeven",
        "distance": None,
        "leerbaan": False,
        "stageplaats": False,
    }
    item.update(overrides)
    return item


def _detail(**overrides: object) -> dict:
    detail: dict = {
        "referenceNumber": 72002335,
        "externalReferenceId": "JOO139178394",
        "employerInternalVacatureId": "139178394",
        "title": "Verpleegkundige Verloskunde",
        "expirationDate": "2026-12-28T00:00:00",
        "modifiedDate": "2026-11-28T00:00:00",
        "createdDate": "2026-10-29T00:00:00",
        "proposition": {
            "termsOfEmploymentDescription": None,
            "workLocation": {
                "type": 1,
                "countryCode": None,
                "postcode": "1181AA",
                "city": "AMSTELVEEN",
                "employerLocationDistance": 0,
            },
            "function": {
                "code": "1000402116",
                "name": "Obstetrisch en gynaecologisch verpleegkundige",
                "description": _DESCRIPTION,
                "customDescription": "Verpleegkundige",
            },
            "salary": {"type": 1, "amountIndication": None},
            "contract": {"type": 1, "startDate": None, "endDate": None},
            "soortTypes": [],
            "workhours": {"minimumHours": 36, "maximumHours": 40, "werktijden": 2},
        },
        "description": None,
        "applicationMethods": [
            {
                "sollicitatieWijze": 4,
                "urlApplicationForm": "https://www.joof.nl/vacature-139178394?sjoof=werk-01",
            }
        ],
        "employer": {
            "organizationName": "Ziekenhuis Amstelland",
            "website": "www.joof.nl",
            "sector": None,
            "addressNetherlands": {"postcode": "5262BR", "city": "VUGHT"},
            "addressForeign": None,
        },
    }
    detail.update(overrides)
    return detail


_UNSET = object()


def _raw(detail: object = _UNSET, **overrides: object) -> RawWerkNlJob:
    payload: dict = {
        "job_id": "72002335",
        "url": "https://www.werk.nl/nl/vacatures/72002335",
        "list_position": 0,
        "list_total": 281590,
        "list_item": _list_item(),
        "detail": _detail() if detail is _UNSET else detail,
    }
    payload.update(overrides)
    return RawWerkNlJob(**payload)


# ---------------------------------------------------------------------------
# Vacancy parsing
# ---------------------------------------------------------------------------


def test_parse_job_maps_a_complete_vacancy() -> None:
    job = WerkNlParser().parse_job(_raw())

    assert job.source_job_id == "72002335"
    assert job.job_title == "Verpleegkundige Verloskunde"
    assert job.company_name == "Ziekenhuis Amstelland"
    assert job.company_logo_url is None
    assert job.location_cleaned == "AMSTELVEEN; NL"
    assert job.salary_disclosed is False
    assert (job.currency_iso_code, job.pay_period) == ("EUR", "monthly")
    assert job.employment_type_code is None
    assert job.posting_date == datetime(2026, 10, 29)
    assert job.closing_date == datetime(2026, 12, 28)
    assert job.apply_url == "https://www.joof.nl/vacature-139178394?sjoof=werk-01"
    assert job.original_url == "https://www.werk.nl/nl/vacatures/72002335"
    assert job.raw_payload["description_source"] == "proposition.function.description"
    assert job.word_count > 10


def test_parse_job_falls_back_to_list_fields_without_a_detail() -> None:
    job = WerkNlParser().parse_job(_raw(detail=None))

    assert job.job_title == "Verpleegkundige Verloskunde"
    assert job.company_name == "Ziekenhuis Amstelland"
    assert job.location_cleaned == "AMSTELVEEN; NL"
    assert job.raw_payload["description_source"] == "structured_summary"
    assert "werk.nl (UWV)" in (job.description_clean or "")
    assert job.apply_url == "https://www.werk.nl/nl/vacatures/72002335"
    assert job.data_quality_score <= 0.6


def test_parse_job_replaces_a_one_word_body_with_the_structured_summary() -> None:
    detail = _detail()
    detail["proposition"]["function"]["description"] = "Schilder"
    job = WerkNlParser().parse_job(_raw(detail))

    assert job.raw_payload["description_source"] == "structured_summary"
    assert "werk.nl (UWV)" in (job.description_clean or "")
    assert "Functie: Obstetrisch en gynaecologisch verpleegkundige" in (job.description_clean or "")
    assert job.data_quality_score <= 0.6


def test_parse_job_keeps_a_five_word_body() -> None:
    detail = _detail()
    detail["proposition"]["function"]["description"] = "Wij zoeken een ervaren schilder."
    job = WerkNlParser().parse_job(_raw(detail))

    assert job.raw_payload["description_source"] == "proposition.function.description"
    assert job.description_clean == "Wij zoeken een ervaren schilder."


def test_parse_job_reads_a_salary_indication() -> None:
    detail = _detail()
    detail["proposition"]["salary"] = {"type": 1, "amountIndication": "€ 3.000 - € 4.000 per maand"}
    job = WerkNlParser().parse_job(_raw(detail))
    assert job.salary_disclosed is True
    assert (job.salary_min, job.salary_max) == (3000.0, 4000.0)


def test_parse_job_maps_tijdelijk_to_temporary() -> None:
    job = WerkNlParser().parse_job(_raw(list_item=_list_item(contractType="Tijdelijk")))
    assert job.employment_type_code == "temporary"


def test_parse_job_keeps_a_foreign_country_token() -> None:
    detail = _detail()
    detail["proposition"]["workLocation"] = {
        "type": 2,
        "countryCode": "BE",
        "postcode": None,
        "city": "Antwerpen",
    }
    job = WerkNlParser().parse_job(_raw(detail))
    assert job.location_cleaned == "Antwerpen; BE"


def test_parse_job_lowercases_a_lowercase_country_code() -> None:
    detail = _detail()
    detail["proposition"]["workLocation"] = {
        "type": 2,
        "countryCode": "be",
        "postcode": None,
        "city": "Antwerpen",
    }
    job = WerkNlParser().parse_job(_raw(detail))
    assert job.location_cleaned == "Antwerpen; BE"


def test_parse_job_falls_back_to_confidential_employer() -> None:
    detail = _detail()
    detail["employer"] = {"organizationName": ""}
    job = WerkNlParser().parse_job(_raw(detail, list_item=_list_item(organisation="")))
    assert job.company_name == "Confidential Employer"


def test_parse_job_drops_a_closing_date_before_the_posting_date() -> None:
    detail = _detail(createdDate="2026-12-01T00:00:00", expirationDate="2026-11-01T00:00:00")
    job = WerkNlParser().parse_job(_raw(detail))
    assert job.closing_date is None


def test_parse_job_rejects_a_vacancy_with_no_title() -> None:
    detail = _detail(title="")
    with pytest.raises(WerkNlParseError):
        WerkNlParser().parse_job(_raw(detail, list_item=_list_item(vacatureTitle="")))


def test_parse_jobs_skips_bad_vacancies_and_keeps_good_ones() -> None:
    good = _raw()
    bad = _raw(
        detail=_detail(title=""),
        job_id="0",
        list_item=_list_item(vacatureTitle=""),
    )
    jobs = WerkNlParser().parse_jobs([good, bad])
    assert [job.source_job_id for job in jobs] == ["72002335"]


# ---------------------------------------------------------------------------
# Page-window selection (no network)
# ---------------------------------------------------------------------------


def _client(**settings: object) -> WerkNlClient:
    return WerkNlClient(WerkNlSettings(inter_request_delay_seconds=0, **settings))


def test_total_pages_respects_the_guard() -> None:
    client = _client()
    assert client.total_pages(0) == 0
    assert client.total_pages(21) == 2
    assert client.total_pages(281590) == 400


def test_select_pages_takes_fresh_pages_then_the_pinned_window() -> None:
    client = _client(fresh_pages=2, start_page=1)
    assert client.select_pages(pages_available=10, budget_pages=4) == [1, 2, 3, 4]


def test_select_pages_returns_everything_when_the_budget_covers_it() -> None:
    client = _client(fresh_pages=2)
    assert client.select_pages(pages_available=3, budget_pages=10) == [1, 2, 3]


def test_rotation_offset_stays_in_range() -> None:
    client = _client()
    offset = client.rotation_offset(100, 10)
    assert 0 <= offset < 100

"""Unit tests for the work.ua (Ukraine) scraper.

No network and no database: every test drives the pure mapping helpers or a
synthetic listing/detail pair built from the shapes measured on 2026-11-28.
The fixtures are constructed here, not copied from a live response, so the
tests describe the contract rather than one capture.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from job_market_intel.scrapers.work_ua import RawWorkUaJob, WorkUaClient, WorkUaSettings
from job_market_intel.scrapers.work_ua.exceptions import WorkUaParseError
from job_market_intel.scrapers.work_ua.parser import (
    WorkUaParser,
    clean_text,
    detect_currency,
    detect_pay_period,
    detect_remote,
    extract_address,
    extract_description,
    map_employment_type,
    parse_amount,
    parse_datetime,
    parse_salary,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_clean_text_collapses_nbsp_and_entities() -> None:
    assert clean_text("  Київ\u00a0,\u202f вулиця  ") == "Київ , вулиця"
    assert clean_text("A &amp; B") == "A & B"
    assert clean_text(None) == ""


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("35 000", 35000.0),
        ("35\u202f000", 35000.0),
        ("1 500,50", 1500.5),
        ("1.500,50", 1500.5),
        ("35.000", 35000.0),
        ("18.40", 18.4),
        ("", None),
        ("грн", None),
    ],
)
def test_parse_amount(token: str, expected: float | None) -> None:
    assert parse_amount(token) == expected


def test_parse_salary_reads_range() -> None:
    assert parse_salary("35 000 – 50 000 грн · Після всіх відрахувань") == (35000.0, 50000.0)


def test_parse_salary_keeps_a_single_number_as_minimum() -> None:
    assert parse_salary("35 000 грн") == (35000.0, None)


def test_parse_salary_returns_none_without_numbers() -> None:
    assert parse_salary("За домовленістю") == (None, None)
    assert parse_salary(None) == (None, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("35 000 грн", "UAH"),
        ("35 000 ₴", "UAH"),
        ("$1 500", "USD"),
        ("1 500 USD", "USD"),
        ("1 500 €", "EUR"),
        ("", "UAH"),
    ],
)
def test_detect_currency(text: str, expected: str) -> None:
    assert detect_currency(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("35 000 грн", "monthly"),
        ("20 000 грн на місяць", "monthly"),
        ("150 грн/год", "hourly"),
        ("за годину 150 грн", "hourly"),
        ("1 500 грн за день", "daily"),
        ("", "monthly"),
    ],
)
def test_detect_pay_period(text: str, expected: str) -> None:
    assert detect_pay_period(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Повна зайнятість · Стандартний графік: 5/2", "full_time"),
        ("Неповна зайнятість", "part_time"),
        ("Часткова зайнятість", "part_time"),
        ("Стажування", "internship"),
        ("Тимчасова робота", "temporary"),
        ("Гнучкий графік", None),
        (None, None),
    ],
)
def test_map_employment_type(text: str | None, expected: str | None) -> None:
    assert map_employment_type(text) == expected


def test_map_employment_type_prefers_part_time_over_the_contained_full_phrase() -> None:
    # "неповна зайнятість" contains "повна зайнятість"; the order must win.
    assert map_employment_type("Неповна зайнятість") == "part_time"


@pytest.mark.parametrize(
    ("address", "title", "description", "expected"),
    [
        ("Київ, вулиця Хрещатик, 1.", "Менеджер", None, "on_site"),
        ("Віддалена робота", "Менеджер", None, "remote_country"),
        (None, "Віддалений менеджер", None, "remote_country"),
        ("Київ", "Менеджер", "Гібридний формат", "hybrid"),
        (None, "Менеджер", None, None),
        # A body-only phrase must not be scanned; the SEO summary is.
        ("Київ", "Менеджер", "Не віддалена робота", "on_site"),
    ],
)
def test_detect_remote(
    address: str | None, title: str | None, description: str | None, expected: str | None
) -> None:
    assert detect_remote(address, title, description) == expected


def test_parse_datetime_reads_the_activation_offset() -> None:
    assert parse_datetime("2026-11-27T17:34:31+02:00") == datetime(2026, 11, 27, 17, 34, 31)
    assert parse_datetime("2026-11-27") == datetime(2026, 11, 27)
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


def _detail_html(
    *,
    salary: str = "35 000 – 50 000 грн · Після всіх відрахувань",
    address_inner: str = (
        "Київ, вулиця Хрещатик, 1."
        '<br/><span class="distance-block"><a>2,0 км від центру</a></span>'
        '<span class="sep">·</span><a data-toggle="job-map" href="javascript:;">На мапі</a>'
    ),
    schedule: str = "Повна зайнятість · Стандартний графік: 5/2",
    description: str = (
        "<p><b>Привіт!</b> Це опис вакансії для тесту.</p>"
        "<ul><li>Обов'язок один</li><li>Обов'язок два</li></ul>"
    ),
    og_description: str = "Робота у Києві, зарплата 35 000 грн, повна зайнятість.",
) -> str:
    return f"""<!DOCTYPE html>
<html lang="uk"><head>
<meta property="og:image" content="https://assets.work.ua/employer_design/1/company_logo_og_v2.png">
<meta property="og:description" content="{og_description}">
</head><body>
<div class="rb" data-company-name="Acme, ТОВ" data-online-at="2026-11-27T17:34:31+02:00"></div>
<h1 class="h2" id="h1-name">Менеджер з продажу</h1>
<ul>
  <li><span class="glyphicon" title="Зарплата"></span><span>{salary}</span></li>
  <li><span class="glyphicon" title="Адреса роботи"></span>{address_inner}</li>
  <li><span class="glyphicon" title="Графік роботи"></span>{schedule}</li>
</ul>
<div class="company-description" id="job-description">{description}</div>
</body></html>"""


def _raw(html: str | None, *, title: str = "Менеджер з продажу") -> RawWorkUaJob:
    return RawWorkUaJob(
        job_id="1234567",
        url="https://www.work.ua/jobs/1234567/",
        list_position=0,
        listing_title=title,
        list_total=86500,
        detail_html=html,
    )


def test_extract_address_drops_distance_and_map_toggle() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_detail_html(), "html.parser")
    assert extract_address(soup) == "Київ, вулиця Хрещатик, 1."


def test_extract_description_keeps_inline_sentence_and_lists() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_detail_html(), "html.parser")
    text = extract_description(soup)
    assert "Привіт! Це опис вакансії для тесту." in text
    assert "Обов'язок один\nОбов'язок два" in text


def test_parse_job_maps_every_measured_field() -> None:
    job = WorkUaParser().parse_job(_raw(_detail_html()))

    assert job.source_job_id == "1234567"
    assert job.job_title == "Менеджер з продажу"
    assert job.company_name == "Acme, ТОВ"
    assert job.company_logo_url == "https://assets.work.ua/employer_design/1/company_logo_og_v2.png"
    assert job.location_cleaned == "Київ, вулиця Хрещатик, 1."
    assert job.salary_min == 35000.0
    assert job.salary_max == 50000.0
    assert job.salary_disclosed is True
    assert job.currency_iso_code == "UAH"
    assert job.pay_period == "monthly"
    assert job.employment_type_code == "full_time"
    assert job.remote_work_type_code == "on_site"
    assert job.posting_date == datetime(2026, 11, 27, 17, 34, 31)
    assert job.closing_date is None
    assert job.word_count > 0
    assert job.raw_payload["salary_raw"].startswith("35 000")
    assert job.raw_payload["has_detail"] is True


def test_parse_job_remote_ad_gets_ukraine_location() -> None:
    html = _detail_html(
        salary="25 000 грн",
        address_inner="Віддалена робота",
        og_description="Віддалена робота в українській команді.",
    )
    job = WorkUaParser().parse_job(_raw(html))
    assert job.remote_work_type_code == "remote_country"
    assert job.location_cleaned == "Україна"
    assert job.salary_max is None


def test_parse_job_without_detail_falls_back_to_the_listing_title() -> None:
    job = WorkUaParser().parse_job(_raw(None, title="Водій категорії C"))
    assert job.job_title == "Водій категорії C"
    assert job.company_name == "Confidential Employer"
    assert job.description_clean is None
    assert job.posting_date is None
    assert job.data_quality_score <= 0.5


def test_parse_job_raises_without_a_title() -> None:
    raw = RawWorkUaJob(
        job_id="1",
        url="https://www.work.ua/jobs/1/",
        list_position=0,
        listing_title="",
        detail_html=None,
    )
    with pytest.raises(WorkUaParseError):
        WorkUaParser().parse_job(raw)


# ---------------------------------------------------------------------------
# Listing extraction
# ---------------------------------------------------------------------------


def _listing_html(ids: list[str], total: str = "86 500 вакансій в Україні") -> str:
    cards = "".join(
        f'<div class="card job-link"><h2><a href="/jobs/{jid}/">Вакансія {jid}</a></h2></div>'
        for jid in ids
    )
    return f"<html><head><title>{total}</title></head><body>{cards}</body></html>"


def test_extract_listing_reads_ids_and_total() -> None:
    client = WorkUaClient(settings=WorkUaSettings(inter_request_delay_seconds=0.0))
    found, total = client._extract_listing(_listing_html(["111", "222", "333"]))
    assert [job_id for job_id, _ in found] == ["111", "222", "333"]
    assert total == 86500


def test_extract_listing_deduplicates_and_ignores_non_ad_links() -> None:
    html = (
        "<html><body>"
        '<div class="card job-link"><h2><a href="/jobs/111/">A</a></h2></div>'
        '<div class="card job-link"><h2><a href="/jobs/111/">A again</a></h2></div>'
        '<a href="/jobs/by-company/9/">Company</a>'
        "</body></html>"
    )
    client = WorkUaClient(settings=WorkUaSettings(inter_request_delay_seconds=0.0))
    found, total = client._extract_listing(html)
    assert [job_id for job_id, _ in found] == ["111"]
    assert total is None


def test_listing_url_always_carries_the_page_query() -> None:
    client = WorkUaClient(settings=WorkUaSettings())
    assert client.listing_url(1) == "https://www.work.ua/jobs/?page=1"
    assert client.listing_url(7) == "https://www.work.ua/jobs/?page=7"
    assert client.detail_url("42") == "https://www.work.ua/jobs/42/"

"""A schema.org ``baseSalary`` must survive as a number, not only as text.

The framework renders a JSON payload into minimal HTML and reads it back with
the ordinary parser, so a mapped salary arrived as the string "EUR 20 - 25
HOUR": the cleaner, which stores a salary only when it sees ``salary_min``/
``salary_max``, reported a published hourly wage as "not disclosed"
(Bundesagentur für Arbeit, 2026-10-29).

``detail_json_salary`` maps the structured parts, the client keeps them on the
``#salary`` node as ``data-salary-*`` attributes, and the parser lifts them
into the raw record. An ad that states its own unit and currency also overrides
the board's default for that record.

Run with:  uv run pytest tests/unit/test_html_scraper_json_salary.py -q
"""

from __future__ import annotations

from datetime import date

from job_market_intel.cleaning.html_scraper_cleaner import (
    HtmlScraperCleaner,
    map_employment_type,
)
from job_market_intel.scrapers.html_scraper.client import mapped_json_html
from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.models import RawHtmlScraperJob
from job_market_intel.scrapers.html_scraper.parser import parse_detail

HOURLY = {
    "title": "Bauhelfer (m/w/d)",
    "hiringOrganization": {"name": "Öz Can Cemil Funk"},
    "jobLocation": {
        "@type": "Place",
        "address": {"addressLocality": "Elsdorf", "addressRegion": "Nordrhein-Westfalen"},
    },
    "employmentType": ["FULL_TIME", "TEMPORARY"],
    "description": "<p>" + "Baustelle " * 40 + "</p>",
    "datePosted": "2026-10-28",
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "EUR",
        "value": {
            "@type": "QuantitativeValue",
            "unitText": "HOUR",
            "minValue": 15,
            "maxValue": 25,
        },
    },
}


def _site_config(**overrides) -> SiteConfig:
    settings = {
        "source_code": "unit_test",
        "source_name": "Unit test board",
        "country": "Germany",
        "base_url": "https://www.example.invalid",
        "listing_path": "/suche?angebotsart=1",
        "selectors": {
            "job_title": "h1",
            "company": "#company",
            "location": "#location",
            "employment_type": "#employment_type",
            "description": "#description",
            "posted_date": "#posted_date",
            "salary": "#salary",
        },
        "detail_json_ld": True,
        "detail_json_map": {
            "title": "title",
            "company": "hiringOrganization.name",
            "location": "jobLocation[].address.addressLocality",
            "employment_type": "employmentType",
            "description": ["description"],
            "posted_date": "datePosted",
        },
        "detail_json_salary": {
            "currency": "baseSalary.currency",
            "min": "baseSalary.value.minValue",
            "max": "baseSalary.value.maxValue",
            "value": "baseSalary.value.value",
            "unit": "baseSalary.value.unitText",
        },
        "currency_iso_code": "EUR",
        "pay_period": "monthly",
    }
    return SiteConfig(**(settings | overrides))


def _parse(payload, **overrides):
    config = _site_config(**overrides)
    html = mapped_json_html(config, payload, "https://www.example.invalid/job/1")
    return parse_detail(
        "unit_test",
        config,
        html,
        url="https://www.example.invalid/job/1",
        job_id="1",
    )


def test_a_list_shaped_location_maps_like_a_single_one() -> None:
    """``jobLocation`` is an object on some ads and a list on others."""
    single = _parse(HOURLY)
    listed = _parse({**HOURLY, "jobLocation": [HOURLY["jobLocation"], HOURLY["jobLocation"]]})

    assert single.location == "Elsdorf"
    assert listed.location == "Elsdorf, Elsdorf"


def test_the_salary_range_becomes_numbers_on_the_raw_record() -> None:
    raw = _parse(HOURLY)

    assert raw.raw["salary_min"] == 15
    assert raw.raw["salary_max"] == 25
    assert raw.raw["salary_unit_text"] == "HOUR"
    assert raw.raw["salary_currency"] == "EUR"
    assert raw.raw["salary_raw"] == "EUR 15 - 25 HOUR"


def test_a_single_value_salary_uses_its_own_bounds() -> None:
    payload = {
        **HOURLY,
        "baseSalary": {
            "currency": "EUR",
            "value": {"unitText": "HOUR", "value": 14},
        },
    }
    raw = _parse(payload)

    assert raw.raw["salary_min"] == 14
    assert raw.raw["salary_max"] == 14


def test_an_ad_without_a_salary_carries_no_numbers() -> None:
    payload = {key: value for key, value in HOURLY.items() if key != "baseSalary"}
    raw = _parse(payload)

    assert "salary_min" not in raw.raw
    assert "salary_max" not in raw.raw


def test_a_board_without_the_salary_map_renders_text_only() -> None:
    raw = _parse(HOURLY, detail_json_salary={})

    assert "salary_min" not in raw.raw


def test_the_ads_own_rate_overrides_the_boards_default_period() -> None:
    cleaned = HtmlScraperCleaner(currency_iso_code="EUR", pay_period="monthly").clean_job(
        _parse(HOURLY)
    )

    assert cleaned.salary_disclosed is True
    assert cleaned.salary_min == 15
    assert cleaned.salary_max == 25
    assert cleaned.pay_period == "hourly"
    assert cleaned.currency_iso_code == "EUR"


def test_the_boards_default_holds_when_the_ad_states_no_rate() -> None:
    payload = {key: value for key, value in HOURLY.items() if key != "baseSalary"}
    cleaned = HtmlScraperCleaner(currency_iso_code="EUR", pay_period="monthly").clean_job(
        _parse(payload)
    )

    assert cleaned.salary_disclosed is False
    assert cleaned.pay_period == "monthly"


def test_the_first_of_several_employment_types_wins() -> None:
    """``["FULL_TIME", "TEMPORARY"]`` is a full-time job, per schema.org."""
    assert map_employment_type("FULL_TIME TEMPORARY") == "full_time"
    assert map_employment_type("FULL_TIME, TEMPORARY") == "full_time"
    assert map_employment_type(["PART_TIME", "TEMPORARY"]) == "part_time"


def test_the_first_listed_type_is_the_primary_one() -> None:
    """Order is the board's, not the map's: the first known code wins."""
    assert map_employment_type("TEMPORARY FULL_TIME") == "temporary"
    assert map_employment_type("PART_TIME TEMPORARY") == "part_time"


def test_an_empty_payload_renders_no_salary_attributes() -> None:
    """A payload with no ``baseSalary`` must not invent one."""
    html = mapped_json_html(_site_config(), {}, "https://www.example.invalid/job/1")

    assert "data-salary-min" not in html
    assert "<div id='salary'></div>" in html


def test_structured_salary_is_opt_in() -> None:
    """A board with no ``detail_json_salary`` renders exactly as before."""
    config = _site_config(detail_json_salary={})
    html = mapped_json_html(config, HOURLY, "https://www.example.invalid/job/1")

    assert "<div id='salary'></div>" in html


def test_a_text_only_salary_stays_undisclosed() -> None:
    """Regression guard for boards mapped without ``detail_json_salary``."""
    job = HtmlScraperCleaner().clean_job(
        RawHtmlScraperJob(
            source_job_id="9",
            title="Storekeeper",
            company_name="CHUB",
            description="Duties " * 60,
            country="Rwanda",
            posted_date=date(2026, 10, 27),
            url="https://example.invalid/advertisements",
            raw={"salary_raw": "RWF 100 000"},
        )
    )

    assert job.salary_disclosed is False
    assert job.pay_period == "monthly"


def test_the_mapped_node_holds_the_attributes_the_parser_reads() -> None:
    config = _site_config()
    html = mapped_json_html(config, HOURLY, "https://www.example.invalid/job/1")

    assert "data-salary-min='15'" in html
    assert "data-salary-max='25'" in html
    assert "data-salary-unit='HOUR'" in html
    assert "data-salary-currency='EUR'" in html
    assert "EUR 15 - 25 HOUR" in html

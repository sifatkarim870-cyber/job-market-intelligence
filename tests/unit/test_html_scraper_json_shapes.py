"""Public JSON feeds that split an ad across records and languages.

Jobbnorge publishes a bare array of jobs from one host, the ad body as a list of
components from another, and each ad in only one of four languages. Sapo Emprego
embeds its listing in an HTML attribute instead of serving anchors. Those shapes
are generic enough to support in the framework rather than in a site-specific
scraper, so they get tests here.

Run with:  uv run pytest tests/unit/test_html_scraper_json_shapes.py -q
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.exceptions import (
    HtmlScraperFetchError,
    HtmlScraperResponseError,
)


def _site_config(**overrides) -> SiteConfig:
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Nowhere",
        base_url="https://example.invalid",
        listing_path="/jobs",
        **overrides,
    )


def test_bare_json_array_is_the_job_list() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            listing_json_path="$",
            listing_json_url="https://api.example.invalid/jobs",
            listing_json_url_template="/stilling/{id}",
        ),
    )

    jobs = client._jobs_from_payload([{"id": 310406, "employer": "Båtsfjord kommune"}])

    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://example.invalid/stilling/310406"
    assert jobs[0]["listing"]["employer"] == "Båtsfjord kommune"


def test_zero_page_pagination_starts_at_zero() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            listing_json_url="https://api.example.invalid/jobs?page={zero_page}&results=50"
        ),
    )

    assert client.listing_data_url(1).endswith("page=0&results=50")
    assert client.listing_data_url(3).endswith("page=2&results=50")


def test_wildcard_path_and_listing_fields_build_the_record() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            detail_json_map={
                "title": "listing.title",
                "company": "listing.employer",
                "description": ["components[].text"],
            }
        ),
    )
    payload = {"components": [{"text": "<p>One</p>"}, {"text": "<p>Two</p>"}]}
    listing = {"title": "Helsefagarbeider", "employer": "Båtsfjord kommune"}

    html = client._json_detail_as_html(payload, "https://example.invalid/jobs/1", listing)

    assert "<p>One</p>" in html
    assert "<p>Two</p>" in html
    assert "Helsefagarbeider" in html
    assert "Båtsfjord kommune" in html


def test_detail_languages_are_tried_in_order(monkeypatch) -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            detail_json_url="https://api.example.invalid/jobs/{id}?lang={language}",
            detail_json_languages=[1, 2, 3],
        ),
    )
    calls: list[str] = []

    def fake_get(url: str) -> str:
        calls.append(url)
        if url.endswith("lang=1") or url.endswith("lang=2"):
            raise HtmlScraperFetchError("not in this language")
        return '{"components": []}'

    monkeypatch.setattr(client, "_get", fake_get)

    payload = client._detail_json_payload("310556")

    assert payload == {"components": []}
    assert calls == [
        "https://api.example.invalid/jobs/310556?lang=1",
        "https://api.example.invalid/jobs/310556?lang=2",
        "https://api.example.invalid/jobs/310556?lang=3",
    ]


def test_embedded_json_attribute_uses_the_items_own_link() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            listing_json_path="$",
            listing_json_selector="search-results-component",
            listing_json_attr=":offers",
            listing_json_url_field="link",
        ),
    )
    html = (
        "<html><body><search-results-component "
        ':offers=\'[{"id": "abc", "link": '
        '"https://example.invalid/offers/gestor?id=abc"}]\'>'
        "</search-results-component></body></html>"
    )

    jobs = client._embedded_json_jobs(html)

    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://example.invalid/offers/gestor?id=abc"
    assert jobs[0]["id"] == "abc"


def test_missing_embedded_json_element_is_an_error() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            listing_json_path="$",
            listing_json_selector="search-results-component",
            listing_json_attr=":offers",
            listing_json_url_field="link",
        ),
    )

    with pytest.raises(HtmlScraperResponseError):
        client._embedded_json_jobs("<html><body>no records</body></html>")

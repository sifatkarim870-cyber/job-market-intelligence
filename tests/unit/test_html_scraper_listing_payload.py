"""Feeds that return the whole posting need no detail fetch.

Jobnet's public BFF answers a search request with every field the parser needs,
description included, while the human-facing ad page is behind MitID. Fetching
it would fail and lose all records, so ``detail_json_from_listing`` maps the
listing item itself. The same API rejects requests without ``x-csrf``, which is
why site configs can add headers.

Run with:  uv run pytest tests/unit/test_html_scraper_listing_payload.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig

PAYLOAD = {
    "jobAds": [
        {
            "jobAdId": "abc-123",
            "title": "Maskinmester",
            "hiringOrgName": "Eksempel A/S",
            "description": "<p>Vi søger en maskinmester.</p>",
            "publicationDate": "2026-10-25T00:00:00+02:00",
        }
    ]
}


def _site_config(**overrides) -> SiteConfig:
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Nowhere",
        base_url="https://example.invalid",
        listing_path="/find-job",
        listing_json_path="jobAds",
        listing_json_id_field="jobAdId",
        listing_json_url_template="/jobannonce/{id}",
        **overrides,
    )


def test_listing_item_is_kept_when_it_is_the_whole_posting() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(
            detail_json_from_listing=True,
            detail_json_map={
                "title": "title",
                "company": "hiringOrgName",
                "description": ["description"],
                "posted_date": "publicationDate",
            },
        ),
    )

    jobs = client._jobs_from_payload(PAYLOAD)

    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://example.invalid/jobannonce/abc-123"
    html = client._json_detail_as_html(jobs[0]["payload"], jobs[0]["url"])
    assert "Maskinmester" in html
    assert "Eksempel A/S" in html
    assert "maskinmester" in html


def test_listing_item_is_not_kept_by_default() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())

    jobs = client._jobs_from_payload(PAYLOAD)

    assert "payload" not in jobs[0]


def test_extra_headers_reach_the_session() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config(extra_headers={"x-csrf": "1"}),
    )

    assert client._session.headers["x-csrf"] == "1"

"""Next.js boards hide their listing in ``__NEXT_DATA__``, not in anchors.

Jobzella's ``/search/jobs`` renders the job cards client-side but ships the
same ten records inside the page's Next.js JSON. The generic client saw zero
anchors and reported "no job links" on a page that was not empty. The
``listing_json_path`` option reads that list and builds detail URLs from the
job IDs; this test pins the extraction so a page with no anchors still yields
postings.

Run with:  uv run pytest tests/unit/test_html_scraper_json_listing.py -q
"""

from __future__ import annotations

import json

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig


def _site_config() -> SiteConfig:
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Nowhere",
        base_url="https://example.invalid",
        listing_json_path="props.pageProps.jobs",
        listing_json_id_field="id",
        listing_json_url_template="/jobs/{id}",
    )


def _client() -> HtmlScraperClient:
    return HtmlScraperClient("unit_test", site_config=_site_config())


def _listing_html(payload: dict) -> str:
    return (
        "<html><body><div id='job-list'></div>"
        f"<script id='__NEXT_DATA__' type='application/json'>{json.dumps(payload)}</script>"
        "</body></html>"
    )


def test_json_listing_builds_detail_urls_from_ids() -> None:
    html = _listing_html(
        {
            "props": {
                "pageProps": {
                    "jobs": [
                        {"id": 12044, "position": {"name": "Architect"}},
                        {"id": 12045, "position": {"name": "Engineer"}},
                        {"id": None, "position": {"name": "No id"}},
                    ]
                }
            }
        }
    )

    jobs = _client()._json_listing_jobs(html)

    assert [job["url"] for job in jobs] == [
        "https://example.invalid/jobs/12044",
        "https://example.invalid/jobs/12045",
    ]


def test_json_listing_returns_nothing_when_the_script_is_missing() -> None:
    assert _client()._json_listing_jobs("<html><body>no data</body></html>") == []


def test_json_listing_returns_nothing_when_the_path_is_wrong() -> None:
    html = _listing_html({"props": {"pageProps": {"other": []}}})

    assert _client()._json_listing_jobs(html) == []


def test_external_json_listing_uses_hydra_member() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config().model_copy(
            update={
                "listing_json_path": "hydra:member",
                "listing_json_url": "https://api.example.invalid/api/jobs",
            }
        ),
    )

    jobs = client._jobs_from_payload(
        {"hydra:member": [{"id": 54482}, {"id": 54483}, {"no_id": True}]}
    )

    assert [job["url"] for job in jobs] == [
        "https://example.invalid/jobs/54482",
        "https://example.invalid/jobs/54483",
    ]


def test_json_detail_renders_mapped_fields_as_html() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=_site_config().model_copy(
            update={
                "detail_json_map": {
                    "title": "title",
                    "company": "companyName",
                    "location": "region.fullName",
                    "description": ["mission", "profile"],
                    "posted_date": "publishedDate",
                }
            }
        ),
    )
    payload = {
        "title": "Architect <senior>",
        "companyName": "ACME",
        "region": {"fullName": "Alger, Algérie"},
        "mission": "<p>Build things</p>",
        "profile": "<p>Five years</p>",
        "publishedDate": "2026-10-22T00:00:00+01:00",
    }

    html = client._json_detail_as_html(payload, "https://example.invalid/jobs/1")

    assert "<h1>Architect &lt;senior&gt;</h1>" in html
    assert "<div id='company'>ACME</div>" in html
    assert "<div id='location'>Alger, Algérie</div>" in html
    assert "<p>Build things</p>" in html
    assert "2026-10-22T00:00:00+01:00" in html

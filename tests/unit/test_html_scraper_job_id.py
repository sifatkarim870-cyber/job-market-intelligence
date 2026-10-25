"""Job IDs must survive trailing slashes and repeated slugs.

zaplata.bg detail URLs look like ``/<category>/<city>/703291/servizen-tehnik/``.
Taking the last path segment returned an empty ID (trailing slash) or a slug
that repeats across cities, so two different ads could collide. ``id_url_regex``
lets a site point at the stable numeric segment instead.

Run with:  uv run pytest tests/unit/test_html_scraper_job_id.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig


def _site_config(**overrides) -> SiteConfig:
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Nowhere",
        base_url="https://example.invalid",
        listing_path="/jobs",
        **overrides,
    )


def test_id_url_regex_reads_the_numeric_segment() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config(id_url_regex=r"/(\d{5,7})/"))

    assert (
        client._job_id_from_url("https://www.example.invalid/sales/sofia/703291/servizen-tehnik/")
        == "703291"
    )


def test_trailing_slash_does_not_produce_an_empty_id() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())

    assert (
        client._job_id_from_url("https://www.example.invalid/jobs/archive-2026/") == "archive-2026"
    )


def test_last_segment_is_used_when_the_regex_does_not_match() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config(id_url_regex=r"/(\d{5,7})/"))

    assert (
        client._job_id_from_url("https://www.example.invalid/jobs/senior-engineer")
        == "senior-engineer"
    )

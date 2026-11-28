"""A board whose pager is disallowed is still covered through many fronts.

Subito.it's robots.txt forbids its ``?o=`` offset pager, so only page 1 of each
category front is readable; walking the national front plus one front per region
reaches a real volume without touching the disallowed parameter.
``SiteConfig.listing_paths`` names the extra fronts walked after
``listing_path``, and single-front sites keep exactly one seed.

Run with:  uv run pytest tests/unit/test_html_scraper_listing_fronts.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.exceptions import HtmlScraperFetchError


def _site_config(**overrides) -> SiteConfig:
    base: dict = {
        "source_code": "unit_test",
        "source_name": "Unit test board",
        "country": "Nowhere",
        "base_url": "https://example.invalid",
        "listing_path": "/a",
        "max_pages": 1,
    }
    base.update(overrides)
    return SiteConfig(**base)


def test_seeds_are_primary_then_extras_deduplicated() -> None:
    client = HtmlScraperClient(
        "unit_test", site_config=_site_config(listing_paths=["/b", "/a", "/c"])
    )

    assert client._listing_seeds() == ["/a", "/b", "/c"]


def test_a_single_front_site_has_one_seed() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())

    assert client._listing_seeds() == ["/a"]


def test_discovery_walks_every_front_and_dedupes() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config(listing_paths=["/b"]))
    calls: list[tuple[int, str | None]] = []

    def fake_fetch(page: int = 1, listing_path: str | None = None):
        calls.append((page, listing_path))
        # Both fronts carry the same shared ad, so it is discovered once.
        return "", [
            {"url": f"https://example.invalid{listing_path}/shared", "id": "shared"},
            {"url": f"https://example.invalid{listing_path}/solo", "id": f"solo{listing_path}"},
        ]

    client.fetch_listing_page = fake_fetch  # type: ignore[method-assign]

    found, failures = client.discover_detail_paths()

    assert calls == [(1, "/a"), (1, "/b")]
    assert failures == {}
    assert sorted(job["id"] for job in found) == ["shared", "solo/a", "solo/b"]


def test_a_failed_front_does_not_stop_the_next() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config(listing_paths=["/b"]))

    def fake_fetch(page: int = 1, listing_path: str | None = None):
        if listing_path == "/a":
            raise HtmlScraperFetchError("boom")
        return "", [{"url": "https://example.invalid/b/1", "id": "b1"}]

    client.fetch_listing_page = fake_fetch  # type: ignore[method-assign]

    found, failures = client.discover_detail_paths()

    assert [job["id"] for job in found] == ["b1"]
    assert "/a page=1" in failures


def test_extra_fronts_render_their_own_url() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())

    assert client.listing_url(1) == "https://example.invalid/a"
    assert client.listing_url(1, "/b") == "https://example.invalid/b"
    assert client.listing_url(2, "/b") == "https://example.invalid/b?page=2"

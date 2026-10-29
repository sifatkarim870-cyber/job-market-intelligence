"""Unit tests for JobsNepal's sitemap-first discovery (2026-10-29).

The board's listing (/top-job) carries 14 postings, while /jobs-sitemap.xml
lists 152 -- so the sitemap is the primary channel and the listing is the
fallback. These tests pin that order, the per-run cap, and the raise when
neither channel yields a posting (the failure mode a Cloudflare challenge
produces, which is why the source was disabled in 2026-10-18).
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.jobsnepal.client import (
    JobsNepalClient,
    extract_sitemap_paths,
)
from job_market_intel.scrapers.jobsnepal.config import JobsNepalSettings
from job_market_intel.scrapers.jobsnepal.exceptions import (
    JobsNepalFetchError,
    JobsNepalResponseError,
)

SITEMAP = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://www.jobsnepal.com/admin-and-finance-officer-144759</loc>"
    "<lastmod>2026-10-29T13:27:00+05:00</lastmod></url>"
    "<url><loc>https://www.jobsnepal.com/sales-representative-144758</loc></url>"
    "<url><loc>https://www.jobsnepal.com/category-sitemap.xml</loc></url>"
    "</urlset>"
)

LISTING = (
    "<html><body>"
    '<a href="/junior-accountant-144757">Junior Accountant</a>'
    '<a href="/accountant-144756">Accountant</a>'
    "</body></html>"
)


def client(**overrides) -> JobsNepalClient:
    settings = JobsNepalSettings(inter_request_delay_seconds=0.0, **overrides)
    return JobsNepalClient(settings)


class TestSitemapParsing:
    def test_ids_come_from_the_url_suffix(self) -> None:
        assert extract_sitemap_paths(SITEMAP) == {
            "144759": "/admin-and-finance-officer-144759",
            "144758": "/sales-representative-144758",
        }

    def test_non_job_locations_are_ignored(self) -> None:
        assert (
            extract_sitemap_paths(
                "<urlset><url><loc>https://www.jobsnepal.com/category-sitemap.xml</loc></url></urlset>"
            )
            == {}
        )

    def test_empty_or_broken_xml_is_empty(self) -> None:
        assert extract_sitemap_paths("") == {}
        assert extract_sitemap_paths("<html><body>Just a moment...</body></html>") == {}


class TestDiscoveryOrder:
    def test_sitemap_is_used_before_the_listing(self) -> None:
        calls: list[str] = []

        def fake_fetch(url: str) -> str:
            calls.append(url)
            return SITEMAP

        c = client(max_jobs_per_run=10)
        c._fetch = fake_fetch  # type: ignore[method-assign]
        found, failures = c.discover_detail_paths()
        assert failures == {}
        assert list(found) == ["144759", "144758"]
        assert found["144759"] == {"path": "/admin-and-finance-officer-144759", "page": 0}
        assert calls == ["https://www.jobsnepal.com/jobs-sitemap.xml"]

    def test_the_run_cap_applies_to_the_sitemap(self) -> None:
        c = client(max_jobs_per_run=1)
        c._fetch = lambda url: SITEMAP  # type: ignore[method-assign]
        found, _ = c.discover_detail_paths()
        assert list(found) == ["144759"]

    def test_listing_is_the_fallback_when_the_sitemap_fails(self) -> None:
        def fake_fetch(url: str) -> str:
            if url.endswith("jobs-sitemap.xml"):
                raise JobsNepalFetchError("sitemap refused")
            return LISTING

        c = client(max_pages=1)
        c._fetch = fake_fetch  # type: ignore[method-assign]
        found, failures = c.discover_detail_paths()
        assert set(found) == {"144757", "144756"}
        assert found["144757"] == {"path": "/junior-accountant-144757", "page": 1}
        assert failures == {"sitemap": "sitemap refused"}

    def test_a_walled_sitemap_and_listing_raise(self) -> None:
        c = client(max_pages=1)
        c._fetch = lambda url: "<html><title>Just a moment...</title></html>"  # type: ignore[method-assign]
        with pytest.raises(JobsNepalResponseError, match="not that the board is empty"):
            c.discover_detail_paths()

    def test_listing_url_keeps_page_one_clean(self) -> None:
        c = client()
        assert c.listing_url(1) == "https://www.jobsnepal.com/top-job"
        assert c.listing_url(2) == "https://www.jobsnepal.com/top-job?page=2"

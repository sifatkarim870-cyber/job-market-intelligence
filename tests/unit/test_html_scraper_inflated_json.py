"""Some boards compress their JSON and give every ad the same page.

Rwanda's MIFOTRA e-recruitment API answers
``GET /api/recruitment/open-advertisements`` with
``{"_data_": {"0": 120, "1": 156, ...}}`` -- the bytes of a zlib stream keyed
by position, which the board's own bundle inflates with pako before parsing.
It also has no per-advertisement page: all open ads live on one screen, so
every record shares a URL and the only identity is the advertisement id in the
payload.

``json_inflate`` handles the envelope, and a listing whose URL was built from
the feed's id now keeps that id instead of re-deriving one from the URL (which
would give every ad the same one).

Run with:  uv run pytest tests/unit/test_html_scraper_inflated_json.py -q
"""

from __future__ import annotations

import json
import zlib

from job_market_intel.scrapers.html_scraper.client import (
    HtmlScraperClient,
    _inflate_indexed_zlib,
)
from job_market_intel.scrapers.html_scraper.config import SiteConfig

ADS = [
    {"id": "2610001381", "positionName": "Storekeeper", "entityName": "CHUB"},
    {"id": "2610001391", "positionName": "Radiographer", "entityName": "CHUB"},
]


def _envelope(payload) -> str:
    stream = zlib.compress(json.dumps(payload).encode("utf-8"))
    return json.dumps({"_data_": {str(index): byte for index, byte in enumerate(stream)}})


def _site_config(**overrides) -> SiteConfig:
    settings = {
        "source_code": "unit_test",
        "source_name": "Unit test board",
        "country": "Rwanda",
        "base_url": "https://recruitment.example.invalid",
        "listing_path": "/applicant/advertisements",
        "listing_json_url": "https://recruitment.example.invalid/api/open-advertisements",
        "listing_json_path": "$",
        "listing_json_id_field": "id",
        "listing_json_url_template": "/applicant/advertisements",
        "detail_json_from_listing": True,
        "detail_json_map": {"title": "positionName", "company": "entityName"},
        "json_inflate": True,
        "max_pages": 1,
        "inter_request_delay_seconds": 0,
    }
    return SiteConfig(**(settings | overrides))


def test_indexed_zlib_envelope_decodes_to_the_payload() -> None:
    decoded = _inflate_indexed_zlib(json.loads(_envelope(ADS)))

    assert decoded == ADS


def test_a_payload_that_is_not_the_envelope_is_left_alone() -> None:
    plain = {"jobs": ADS}

    assert _inflate_indexed_zlib(plain) is plain


def test_a_broken_envelope_does_not_raise() -> None:
    """A board that starts compressing only some answers must not crash."""
    broken = {"_data_": {"0": 120, "1": 156, "2": 3}}

    assert _inflate_indexed_zlib(broken) == broken


def test_inflating_is_opt_in() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config(json_inflate=False))

    assert client._maybe_inflate({"jobs": ADS}) == {"jobs": ADS}
    assert client._maybe_inflate({"jobs": ADS}) != ADS


def test_the_listing_is_read_through_the_envelope(monkeypatch) -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())
    monkeypatch.setattr(client, "_get", lambda url: _envelope(ADS))

    _, jobs = client.fetch_listing_page(1)

    assert [job["id"] for job in jobs] == ["2610001381", "2610001391"]


def test_a_shared_page_keeps_every_posting(monkeypatch) -> None:
    """One page URL for all ads must not collapse them into a single record."""
    client = HtmlScraperClient("unit_test", site_config=_site_config())
    monkeypatch.setattr(client, "_get", lambda url: _envelope(ADS))

    _, jobs = client.fetch_listing_page(1)

    assert {job["url"] for job in jobs} == {
        "https://recruitment.example.invalid/applicant/advertisements"
    }
    assert len(jobs) == 2


def test_the_feed_id_names_the_posting_not_the_shared_url(monkeypatch) -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())
    monkeypatch.setattr(client, "_get", lambda url: _envelope(ADS))

    records, failures = client.fetch_raw_jobs(max_jobs=2)

    assert failures == {}
    assert [record["job_id"] for record in records] == ["2610001381", "2610001391"]
    assert "Storekeeper" in records[0]["html"]

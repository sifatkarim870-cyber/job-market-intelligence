"""Cards that navigate with JavaScript instead of an anchor.

Serbia's NSZ job search renders every result as

    <div class="single-job">
      <div onclick="document.location.href='https://nsz.gov.rs/.../104483'"> ... </div>
    </div>

with no ``<a href>`` anywhere, so a CSS link selector matches elements that
carry no ``href`` and the board looks empty. ``listing_link_attr`` reads the URL
out of the attribute and ``listing_link_regex`` cuts it from the JS.

Run with:  uv run pytest tests/unit/test_html_scraper_listing_link_attr.py -q
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig

LISTING_HTML = """
<html><body>
  <div class="single-job">
    <div class="clickable"
         onclick="document.location.href='https://example.invalid/jobs/preview/104483'">
      <h3 class="job-title">Role A</h3>
    </div>
  </div>
  <div class="single-job">
    <div class="clickable"
         onclick="document.location.href='https://example.invalid/jobs/preview/104482'">
      <h3 class="job-title">Role B</h3>
    </div>
  </div>
</body></html>
"""


def _config(**overrides) -> SiteConfig:
    fields = {
        "source_code": "unit_test",
        "source_name": "Unit test board",
        "country": "Serbia",
        "base_url": "https://example.invalid",
        "listing_path": "/employee/jobs/search",
        "selectors": {"job_link": ".single-job .clickable"},
        "listing_link_attr": "onclick",
        "listing_link_regex": "href='([^']+)'",
    }
    fields.update(overrides)
    return SiteConfig(**fields)


def _jobs(config: SiteConfig) -> list[dict]:
    client = HtmlScraperClient("unit_test", site_config=config)
    return client._html_listing_jobs(LISTING_HTML, BeautifulSoup(LISTING_HTML, "html.parser"))


def test_onclick_cards_yield_detail_urls() -> None:
    jobs = _jobs(_config())

    assert [job["url"] for job in jobs] == [
        "https://example.invalid/jobs/preview/104483",
        "https://example.invalid/jobs/preview/104482",
    ]


def test_without_a_regex_the_attribute_is_the_url() -> None:
    html = (
        '<html><body><div class="single-job"><div class="clickable"'
        ' data-url="https://example.invalid/jobs/7">x</div></div></body></html>'
    )
    config = _config(listing_link_attr="data-url", listing_link_regex="")

    client = HtmlScraperClient("unit_test", site_config=config)
    jobs = client._html_listing_jobs(html, BeautifulSoup(html, "html.parser"))

    assert [job["url"] for job in jobs] == ["https://example.invalid/jobs/7"]


def test_off_by_default_no_anchor_means_no_jobs() -> None:
    config = _config(listing_link_attr="", listing_link_regex="")

    assert _jobs(config) == []

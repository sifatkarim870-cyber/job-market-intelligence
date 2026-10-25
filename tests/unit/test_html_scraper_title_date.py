"""Headings with a badge, and dates printed behind a label.

Empleos.net renders the posting title as
``<h3>Contador <small>Vacante Fresca</small></h3>`` and the date as
``<li>Publicado el: 23-10-2026, por Acme.</li>``. Neither can be separated with
CSS alone: the first stored the badge as part of the job title and the second
stored no date at all. ``title_strip_selector`` and ``posted_date_regex`` are
the two per-site answers.

Run with:  uv run pytest tests/unit/test_html_scraper_title_date.py -q
"""

from __future__ import annotations

from datetime import date

from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.parser import HtmlScraperParser

DETAIL_HTML = (
    """
<html><body>
  <div class="xblog-medium-info">
    <h3 class="text-primary">Contador <small class="label">Vacante Fresca</small></h3>
    <h4>Acme S.A.</h4>
    <ul class="xblog-medium-info-meta">
      <li class="xblog-medium-info-meta-item">
        <strong>Publicado el:</strong> 23-10-2026,
      </li>
    </ul>
  </div>
  <h4>Ubicación del Puesto</h4>
  <p>Heredia, Costa Rica</p>
  <div class="pr-20 pt-20 pb-20">
    <p>"""
    + ("Requisitos del puesto. " * 20)
    + """</p>
  </div>
</body></html>
"""
)


def _site_config(**overrides) -> SiteConfig:
    selectors = {
        "job_title": "div.xblog-medium-info h3",
        "company": "div.xblog-medium-info h4",
        "location": "h4:-soup-contains('Ubicación del Puesto') + p",
        "description": "div.pr-20.pt-20.pb-20",
        "posted_date": "li.xblog-medium-info-meta-item",
    }
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Costa Rica",
        base_url="https://example.invalid",
        listing_path="/vacantes",
        selectors=selectors,
        title_priority="selector,og:title",
        **overrides,
    )


def _parse(config: SiteConfig):
    parser = HtmlScraperParser(config, "unit_test")
    return parser.parse(
        "123_contador", DETAIL_HTML, url="https://example.invalid/puesto/123_contador"
    )


def test_title_strip_selector_drops_the_badge() -> None:
    job = _parse(_site_config(title_strip_selector="small"))

    assert job.title == "Contador"


def test_badge_stays_when_no_strip_selector_is_configured() -> None:
    job = _parse(_site_config())

    assert job.title == "Contador Vacante Fresca"


def test_posted_date_regex_finds_the_date_behind_the_label() -> None:
    job = _parse(_site_config(posted_date_regex=r"\d{2}-\d{2}-\d{4}"))

    assert job.posted_date == date(2026, 10, 23)


def test_label_without_the_regex_yields_no_date() -> None:
    job = _parse(_site_config())

    assert job.posted_date is None

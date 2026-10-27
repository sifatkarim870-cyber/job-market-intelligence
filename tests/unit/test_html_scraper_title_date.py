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


# --- Gleaner Classifieds: untitled ads, and a date kept in an attribute -------

GLEANER_HTML = """
<html><body>
  <div class="middlebar" id="details">
    <div class="panel-heading">
      <h1><span class="sr_ad_title" itemprop="name">
        <a href="/marketplace/advert/-Recruitment_29693"></a>
      </span></h1>
    </div>
    <div class="linkify adDescDetails">
      Seeking fulltime Goat Farmer in Portmore area. 876-356-8185
    </div>
    <span class="time-stamp">
      <time datetime="2026-10-25 00:00:00.0">Post Date: 10/25 12:00 AM</time>
    </span>
  </div>
</body></html>
"""


def _gleaner_config(**overrides) -> SiteConfig:
    selectors = {
        "job_title": "h1 .sr_ad_title",
        "description": ".adDescDetails",
        "posted_date": ".time-stamp time@datetime",
    }
    return SiteConfig(
        source_code="jamaica_gleaner_com",
        source_name="Gleaner Classifieds",
        country="Jamaica",
        base_url="https://www.gleanerclassifieds.com",
        listing_path="/marketplace/category/020-vacancies/022-vacancies-general",
        selectors=selectors,
        detail_url_pattern=r"/marketplace/advert/[^/]+$",
        **overrides,
    )


def _parse_gleaner(config: SiteConfig):
    return HtmlScraperParser(config, "jamaica_gleaner_com").parse(
        "-Recruitment_29693",
        GLEANER_HTML,
        url="https://www.gleanerclassifieds.com/marketplace/advert/-Recruitment_29693",
    )


def test_attribute_selector_reads_the_time_datetime() -> None:
    job = _parse_gleaner(_gleaner_config())

    assert job.posted_date == date(2026, 10, 25)


def test_time_element_text_alone_carries_no_year() -> None:
    text_only = _gleaner_config()
    text_only.selectors.posted_date = ".time-stamp time"

    job = _parse_gleaner(text_only)

    # The visible label is "Post Date: 10/25 12:00 AM", which has no year; the
    # datetime attribute read above is what makes the date parseable.
    assert job.posted_date is None


def test_untitled_ad_falls_back_to_url_slug_by_default() -> None:
    job = _parse_gleaner(_gleaner_config())

    # The slug names nothing useful here, which is why the site opts in below.
    assert job.title == "Recruitment 29693"


def test_title_from_description_names_an_untitled_ad() -> None:
    job = _parse_gleaner(_gleaner_config(title_from_description=True))

    assert job.title == "Seeking fulltime Goat Farmer in Portmore area"

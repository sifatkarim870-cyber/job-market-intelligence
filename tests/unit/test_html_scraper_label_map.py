"""Facts printed as label/value rows, and the Estonian date format.

Töötukassa renders each fact as a label beside its value in a ``<li>`` whose
container has no class of its own::

    <li><span>Töökoha asukoht</span><div><p>Harju maakond, Maardu linn</p></div></li>
    <li><span>Töötasu (bruto)</span><span>alates 1970 EUR</span></li>
    <li><span>Tööaeg</span><div><span>Täistööaeg</span></div></li>

A CSS selector cannot say "the value next to this label" without pinning
Tailwind classes that change on every deploy, so ``detail_label_map`` names the
label and the parser reads its sibling. The same shape appears on ``<dt>`` /
``<dd>`` boards, which the helper also covers.

The posted date needs its own note: Töötukassa prints ``Avaldati: 28.10.2026``
and ``_parse_date`` had no ``%d.%m.%Y`` format, so a correct date parsed to
``None``.

Run with:  uv run pytest tests/unit/test_html_scraper_label_map.py -q
"""

from __future__ import annotations

from datetime import date

from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.parser import HtmlScraperParser, _parse_date

DETAIL_HTML = (
    """
<html><body>
  <div class="page-content">
    <div class="flex-1"><h2>Lasteaed Sipsik</h2></div>
    <h1>Eripedagoog</h1>
    <p>Ootame oma meeskonda hoolivat ja uuendusmeelset eripedagoogi.</p>
    <div class="mt-2 text-base leading-6">
      Avaldati: 28.10.2026 <span> - Tööpakkumise nr: 1667201 </span>
    </div>
    <div class="order-3">
      <h2>Tööülesanded</h2>
      <p>"""
    + ("Laste arengu toetamine ja õpioskuste hindamine. " * 10)
    + """</p>
      <ul class="no-list">
        <li><span> Töökoha asukoht </span>
            <div><p> Harju maakond, Maardu linn </p></div></li>
        <li><span> Töötasu (bruto) </span><span> alates 1970 EUR </span></li>
        <li><span> Tööaeg </span><div><span> Täistööaeg </span></div></li>
      </ul>
    </div>
  </div>
</body></html>
"""
)

DEFINITION_HTML = (
    """
<html><body>
  <h1>Kokk</h1>
  <div class="description">"""
    + ("Värskete pagaritoodete valmistamine ja köögi korrashoid. " * 10)
    + """</div>
  <dl>
    <dt>Location</dt><dd>Tartu</dd>
    <dt>Employment type</dt><dd>Full-time</dd>
  </dl>
</body></html>
"""
)


def _site_config(**overrides) -> SiteConfig:
    fields = {
        "source_code": "unit_test",
        "source_name": "Unit test board",
        "country": "Estonia",
        "base_url": "https://example.invalid",
        "listing_path": "/toopakkumised",
        "selectors": {
            "job_title": "div.page-content h1",
            "company": "div.page-content div.flex-1 > h2",
            "location": "",
            "employment_type": "",
            "description": "div.page-content",
            "posted_date": "div.page-content div.mt-2.text-base",
            "salary": "",
        },
        "title_priority": "selector,og:title",
        "detail_label_map": {
            "location": "Töökoha asukoht",
            "salary": "Töötasu (bruto)",
            "employment_type": "Tööaeg",
        },
        "posted_date_regex": r"\d{2}\.\d{2}\.\d{4}",
    }
    fields.update(overrides)
    return SiteConfig(**fields)


def test_labels_fill_the_fields_no_selector_can_reach() -> None:
    job = HtmlScraperParser(_site_config(), "unit_test").parse(
        "eripedagoog-842329",
        DETAIL_HTML,
        url="https://example.invalid/et/toopakkumised/eripedagoog-842329",
    )

    assert job.title == "Eripedagoog"
    assert job.company_name == "Lasteaed Sipsik"
    assert job.location == "Harju maakond, Maardu linn"
    assert job.employment_type == "Täistööaeg"
    assert job.raw["salary_raw"] == "alates 1970 EUR"
    assert job.posted_date == date(2026, 10, 28)


def test_definition_list_shape_is_read_too() -> None:
    config = _site_config(
        selectors={
            "job_title": "h1",
            "company": "",
            "location": "",
            "employment_type": "",
            "description": "div.description",
            "posted_date": "",
            "salary": "",
        },
        detail_label_map={"location": "Location", "employment_type": "Employment type"},
        posted_date_regex="",
    )

    job = HtmlScraperParser(config, "unit_test").parse(
        "1", DEFINITION_HTML, url="https://example.invalid/jobs/1"
    )

    assert job.location == "Tartu"
    assert job.employment_type == "Full-time"


def test_a_selector_that_produced_a_value_wins_over_the_label() -> None:
    """A label can appear twice on one page; the site-specific selector is the
    deliberate answer and must not be overwritten by a later match."""
    config = _site_config(
        selectors={
            "job_title": "div.page-content h1",
            "company": "div.page-content div.flex-1 > h2",
            "location": "div.order-3 h2",
            "employment_type": "",
            "description": "div.page-content",
            "posted_date": "",
            "salary": "",
        }
    )

    job = HtmlScraperParser(config, "unit_test").parse(
        "1", DETAIL_HTML, url="https://example.invalid/et/toopakkumised/1"
    )

    assert job.location == "Tööülesanded"


def test_estonian_dotted_date_parses() -> None:
    assert _parse_date("28.10.2026") == date(2026, 10, 28)
    assert _parse_date("01.01.2027") == date(2027, 1, 1)
    assert _parse_date("31.02.2026") is None

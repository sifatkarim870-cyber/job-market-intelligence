"""JSON-LD blocks that are almost, but not quite, valid JSON.

Chile's BNE publishes the schema.org ``JobPosting`` for every ad but leaves raw
line breaks inside the description string, which strict JSON rejects. The
listing feed also HTML-escapes its titles ("Copiap&oacute;"), so mapped text has
to be unescaped before it is rendered. Both behaviours live in the framework
and get tests here.

Run with:  uv run pytest tests/unit/test_html_scraper_json_ld.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.client import (
    HtmlScraperClient,
    _json_ld_job_posting,
)
from job_market_intel.scrapers.html_scraper.config import SiteConfig


def test_json_ld_with_raw_line_breaks_is_accepted() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@context": "http://schema.org/", "@type": "JobPosting",'
        ' "title": "Dimensionador",'
        ' "description": "<p>Primera linea\nSegunda linea</p>"}'
        "</script>"
    )

    payload = _json_ld_job_posting(html)

    assert payload is not None
    assert payload["title"] == "Dimensionador"
    assert "Segunda linea" in payload["description"]


def test_mapped_text_unescapes_html_entities() -> None:
    client = HtmlScraperClient(
        "unit_test",
        site_config=SiteConfig(
            source_code="unit_test",
            source_name="Unit test board",
            country="Chile",
            base_url="https://example.invalid",
            listing_path="/ofertas",
            detail_json_map={
                "title": "listing.titulo",
                "description": ["description"],
            },
        ),
    )

    html = client._json_detail_as_html(
        {"description": "<p>Misión del cargo</p>"},
        "https://example.invalid/oferta/1",
        {"titulo": "Operador de gr&uacute;a"},
    )

    assert "Operador de grúa" in html
    assert "&amp;uacute;" not in html

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


def test_unescaped_html_attribute_quotes_inside_the_description_are_repaired() -> None:
    """emploi.ma publishes inline HTML whose attribute quotes are not escaped.

    ``data-olk-copy-source="MessageBody"`` inside the description string breaks
    JSON parsing, which used to discard the whole block -- and with it the
    company, location and dates -- even though only one field was malformed.
    """
    html = (
        '<script type="application/ld+json">\n'
        "{\n"
        '  "@context": "http://schema.org/",\n'
        '  "@type": "JobPosting",\n'
        '  "title": "Technicien Regleur",\n'
        '  "description": "<p>Nous recrutons.</p>'
        '<p><b data-olk-copy-source="MessageBody">Missions :</b></p>",\n'
        '  "hiringOrganization": {"@type": "Organization", "name": "AISCAN"},\n'
        '  "jobLocation": {"@type": "Place", "address": {"addressLocality": "Tanger"}}\n'
        "}\n"
        "</script>"
    )

    payload = _json_ld_job_posting(html)

    assert payload is not None
    assert payload["hiringOrganization"]["name"] == "AISCAN"
    assert payload["jobLocation"]["address"]["addressLocality"] == "Tanger"
    assert 'data-olk-copy-source="MessageBody"' in payload["description"]


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

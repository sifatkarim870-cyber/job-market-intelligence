"""A page that prints its body in markup and its facts in a JSON-LD summary.

Slovakia's HelloWorld renders the full ad body as ordinary ``.__job-text-body``
markup, but names neither the posted date (the header clock is the application
deadline, i.e. ``validThrough``) nor, on some ads, the employer in a form a CSS
selector reaches. The detail page also carries the schema.org ``JobPosting``
block with ``datePosted`` / ``hiringOrganization`` / ``jobLocation``.

``detail_json_ld`` would replace the whole page with that block and lose the
body; ``detail_json_ld_fill`` instead keeps the real markup for the description
and fills only the fields the selectors left empty. These tests pin that
gap-only behaviour.

Run with:  uv run pytest tests/unit/test_html_scraper_json_ld_fill.py -q
"""

from __future__ import annotations

import json
from datetime import date

from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.parser import HtmlScraperParser

BODY = "U Subotici, podrška pri preseljenju. " * 12

DETAIL_HTML = (
    """
<html><body>
  <h1>Produkt dizajner</h1>
  <div class="__job-header"><p class="city">Subotica</p></div>
  <div class="__job-text-body">"""
    + BODY
    + """</div>
  <script type="application/ld+json">
  """
    + json.dumps(
        {
            "@context": "http://schema.org/",
            "@type": "JobPosting",
            "title": "Produkt dizajner",
            "description": "Kompanija 4Zida raspisuje oglas za poziciju Produkt dizajner.",
            "datePosted": "2026-10-19",
            "validThrough": "2026-11-12T00:00:00",
            "hiringOrganization": {"@type": "Organization", "name": "4Zida - deo Inspira grupe"},
            "jobLocation": {
                "@type": "Place",
                "address": {"@type": "PostalAddress", "addressLocality": "Novi Sad"},
            },
        }
    )
    + """
  </script>
</body></html>
"""
)


def _config(**overrides) -> SiteConfig:
    fields = {
        "source_code": "unit_test",
        "source_name": "Unit test board",
        "country": "Serbia",
        "base_url": "https://example.invalid",
        "listing_path": "/oglasi-za-posao/",
        "selectors": {
            "job_title": "h1",
            # Company is left to the JSON-LD block: the real board prints the
            # employer as a classless ``<h4>`` on some ads and as a link on
            # others, and this ad carries neither.
            "company": "",
            "location": "",
            "description": ".__job-text-body",
            "posted_date": "",
            "salary": "",
        },
        "detail_json_ld_fill": True,
    }
    fields.update(overrides)
    return SiteConfig(**fields)


def test_json_ld_fill_names_fields_the_markup_leaves_empty() -> None:
    job = HtmlScraperParser(_config(), "unit_test").parse(
        "762454",
        DETAIL_HTML,
        url="https://example.invalid/posao/Produkt-dizajner/4Zida/762454",
    )

    assert job.company_name == "4Zida - deo Inspira grupe"
    assert job.location == "Novi Sad"
    assert job.posted_date == date(2026, 10, 19)


def test_the_markup_body_is_kept_not_the_json_ld_summary() -> None:
    """``detail_json_ld_fill`` must not swap the full body for the block's
    one-sentence ``description``."""
    job = HtmlScraperParser(_config(), "unit_test").parse(
        "762454",
        DETAIL_HTML,
        url="https://example.invalid/posao/Produkt-dizajner/4Zida/762454",
    )

    assert job.description is not None
    assert len(job.description) > len(BODY) - 50
    assert "raspisuje oglas" not in job.description


def test_a_selector_that_produced_a_value_wins_over_json_ld() -> None:
    """Only gaps are filled: a CSS selector written for this site is deliberate
    and must not be overwritten by the block."""
    config = _config(
        selectors={
            "job_title": "h1",
            "company": "",
            "location": ".__job-header p.city",
            "description": ".__job-text-body",
            "posted_date": "",
            "salary": "",
        }
    )

    job = HtmlScraperParser(config, "unit_test").parse(
        "762454",
        DETAIL_HTML,
        url="https://example.invalid/posao/Produkt-dizajner/4Zida/762454",
    )

    # The markup says Subotica; the block says Novi Sad.
    assert job.location == "Subotica"


def test_fill_is_off_by_default() -> None:
    config = _config(detail_json_ld_fill=False)

    job = HtmlScraperParser(config, "unit_test").parse(
        "762454",
        DETAIL_HTML,
        url="https://example.invalid/posao/Produkt-dizajner/4Zida/762454",
    )

    assert job.company_name == "Unknown employer"
    assert job.location is None
    assert job.posted_date is None

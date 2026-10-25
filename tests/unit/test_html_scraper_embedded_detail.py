"""Inertia pages ship the posting as JSON, not as markup.

agenceemploijeunes.ci is a Laravel/Inertia app: the server sends an empty
``<div id="app">`` and the whole page payload in its ``data-page`` attribute,
so there are no anchors to discover and no elements to select. The detail page
is read from that attribute and mapped through ``detail_json_map``, while the
publication date (absent from the ad object itself) comes from the listing
item.
"""

from __future__ import annotations

import json

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.parser import HtmlScraperParser

OFFRE = {
    "id": "KORH-180639-10-2026",
    "titre": "Stagiaire Assistant Comptable/Korhogo",
    "entreprise": "ILCOFORM-SARL",
    "localisation": "KORHOGO",
    "description": "<p>Dans le cadre du renforcement de son service Comptabilité.</p>",
    "description_taches": "<ul><li>Classer les pièces comptables.</li></ul>",
    "salaire": None,
}
LISTING_ITEM = {"slug": "KORH-180639-10-2026", "date_publication": "2026-10-23"}


def _page(props: dict) -> str:
    payload = json.dumps(
        {"component": "OffreEmploiDetails", "props": props}, ensure_ascii=False
    ).replace("'", "&#39;")
    return f"<html><body><div id='app' data-page='{payload}'></div></body></html>"


def _site_config(**overrides) -> SiteConfig:
    defaults = dict(
        source_code="unit_test",
        source_name="Unit test board",
        country="Côte d'Ivoire",
        base_url="https://example.invalid",
        listing_path="/offres-emploi?show_all=1",
        selectors={
            "job_title": "h1",
            "company": "#company",
            "location": "#location",
            "description": "#description",
            "posted_date": "#posted_date",
            "salary": "#salary",
        },
        detail_json_selector="div#app[data-page]",
        detail_json_attr="data-page",
        detail_json_path="props.offre",
        detail_json_map={
            "title": "titre",
            "company": "entreprise",
            "location": "localisation",
            "description": ["description", "description_taches"],
            "posted_date": "listing.date_publication",
            "salary": "salaire",
        },
    )
    defaults.update(overrides)
    return SiteConfig(**defaults)


def test_embedded_detail_json_reads_the_posting_path() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())

    payload = client._embedded_detail_json(_page({"offre": OFFRE}))

    assert payload["titre"] == "Stagiaire Assistant Comptable/Korhogo"


def test_embedded_detail_json_is_rendered_and_parsed() -> None:
    config = _site_config()
    client = HtmlScraperClient("unit_test", site_config=config)
    parser = HtmlScraperParser(config, "unit_test")

    payload = client._embedded_detail_json(_page({"offre": OFFRE}))
    html = client._mapped_json_html(
        payload, "https://example.invalid/offres-emploi/KORH-180639-10-2026", LISTING_ITEM
    )
    job = parser.parse(
        "KORH-180639-10-2026",
        html,
        url="https://example.invalid/offres-emploi/KORH-180639-10-2026",
    )

    assert job.title == "Stagiaire Assistant Comptable/Korhogo"
    assert job.company_name == "ILCOFORM-SARL"
    assert job.location == "KORHOGO"
    assert job.posted_date is not None and job.posted_date.isoformat() == "2026-10-23"
    assert "Comptabilité" in (job.description or "")
    assert "Classer les pièces comptables" in (job.description or "")


def test_missing_detail_path_is_an_error_not_an_empty_record() -> None:
    import pytest

    from job_market_intel.scrapers.html_scraper.exceptions import HtmlScraperResponseError

    client = HtmlScraperClient(
        "unit_test", site_config=_site_config(detail_json_path="props.missing")
    )

    with pytest.raises(HtmlScraperResponseError):
        client._embedded_detail_json(_page({"offre": OFFRE}))

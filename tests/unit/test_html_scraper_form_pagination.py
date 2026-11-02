"""A search whose paging is a form POST, not a ``?page=N`` URL.

Portugal's IEFP renders its next page from the search form's own submit
button: the button rewrites ``currentPage``/``pos`` hidden inputs and POSTs the
whole form back to the same ``search.do`` action. The generic client only knew
how to GET ``listing_pagination``, so page 2 repeated page 1 forever.

``listing_form_pagination`` names the fields to override, and the client reads
the form once (its action and every hidden field) before resending it. This
test pins both halves: the first page is a GET, and the second is a POST to the
form's own action carrying the configured overrides.

Run with:  uv run pytest tests/unit/test_html_scraper_form_pagination.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig

FIRST_PAGE = """
<html><body>
<form name="pesquisaForm" action="/search.do;jsessionid=ABC123">
  <input type="hidden" name="action" value="">
  <input type="hidden" name="tipo" value="OFERTA_EMPREGO">
  <input type="hidden" name="currentPage" value="1">
  <input type="hidden" name="pos" value="0">
  <input type="hidden" name="resultsPerPage" value="10">
  <a href="IEFP/pesquisas/detalheOfertas2.do?idOferta=111&posAbs=1">Mais Detalhes</a>
</form>
</body></html>
"""

SECOND_PAGE = """
<html><body>
<a href="IEFP/pesquisas/detalheOfertas2.do?idOferta=222&posAbs=11">Mais Detalhes</a>
</body></html>
"""


def _site_config() -> SiteConfig:
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Nowhere",
        base_url="https://example.invalid",
        listing_path="/search.do",
        listing_page_size=10,
        listing_form_selector="form[name='pesquisaForm']",
        listing_form_pagination={
            "action": "5",
            "pos": "{offset}",
            "currentPage": "{page}",
            "resultsPerPage": "{page_size}",
        },
        selectors={"job_link": "a[href*='detalheOfertas']"},
    )


def test_form_pagination_posts_hidden_fields_with_page_overrides() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())
    posts: list[tuple[str, dict[str, str]]] = []

    client._get = lambda url: FIRST_PAGE  # type: ignore[method-assign]

    def fake_post(url: str, fields: dict[str, str]) -> str:
        posts.append((url, fields))
        return SECOND_PAGE

    client._post_form = fake_post  # type: ignore[method-assign]

    first_html, first_jobs = client.fetch_listing_page(1)
    second_html, second_jobs = client.fetch_listing_page(2)

    assert first_html == FIRST_PAGE
    assert [job["url"] for job in first_jobs] == [
        "https://example.invalid/IEFP/pesquisas/detalheOfertas2.do?idOferta=111&posAbs=1"
    ]
    assert [job["url"] for job in second_jobs] == [
        "https://example.invalid/IEFP/pesquisas/detalheOfertas2.do?idOferta=222&posAbs=11"
    ]

    assert len(posts) == 1
    url, fields = posts[0]
    assert url == "https://example.invalid/search.do;jsessionid=ABC123"
    # Hidden fields survive untouched; only the configured ones are rewritten.
    assert fields["tipo"] == "OFERTA_EMPREGO"
    assert fields["action"] == "5"
    assert fields["pos"] == "10"
    assert fields["currentPage"] == "2"
    assert fields["resultsPerPage"] == "10"


def test_form_pagination_does_not_fetch_page_one_twice() -> None:
    client = HtmlScraperClient("unit_test", site_config=_site_config())
    gets: list[str] = []
    client._get = lambda url: gets.append(url) or FIRST_PAGE  # type: ignore[method-assign]
    client._post_form = lambda url, fields: SECOND_PAGE  # type: ignore[method-assign]

    client.fetch_listing_page(1)
    client.fetch_listing_page(2)

    assert gets == ["https://example.invalid/search.do"]

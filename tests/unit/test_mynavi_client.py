"""Discovery for Mynavi, whose postings are only reachable through a sitemap.

Mynavi's search is a query-string application that robots.txt disallows for
``User-agent: *`` (``Disallow: /*?``), so the generic listing path cannot see a
single posting. What a crawler is allowed to read is the published company
sitemap; each company page lists its recruitment courses, and each course has
an equivalent query-free detail URL. These tests pin that translation.

Run with:  uv run pytest tests/unit/test_mynavi_client.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.config import HtmlScraperSettings, SiteConfig
from job_market_intel.scrapers.mynavi import MynaviClient

SITEMAP = """<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://job.mynavi.jp/27/pc/search/corp2/employment.html</loc></url>
  <url><loc>https://job.mynavi.jp/27/pc/search/corp211619/employment.html</loc></url>
  <url><loc>https://job.mynavi.jp/27/pc/search/corp211619/outline.html</loc></url>
</urlset>
"""

COMPANY_PAGE = """
<html><body>
  <h3>募集コース一覧</h3>
  <a href="/27/pc/corpinfo/displayEmployment/index/?corpId=211619&recruitingCourseId=27037949">
    営業職コース
  </a>
  <a href="/27/pc/corpinfo/displayEmployment/index/?corpId=211619&amp;recruitingCourseId=27058549">
    営業 兼 施工管理コース
  </a>
</body></html>
"""


def _site_config() -> SiteConfig:
    return SiteConfig(
        source_code="job_mynavi_jp",
        source_name="Mynavi",
        country="Japan",
        base_url="https://job.mynavi.jp",
        max_jobs_per_run=4,
        inter_request_delay_seconds=0.0,
    )


class _StubClient(MynaviClient):
    """Answers from the fixtures above; records what discovery asked for."""

    def __init__(self) -> None:
        settings = HtmlScraperSettings()
        super().__init__("job_mynavi_jp", settings, _site_config())
        self.requested: list[str] = []

    def _get(self, url: str) -> str:
        self.requested.append(url)
        if url.endswith(".xml"):
            return SITEMAP
        return COMPANY_PAGE

    def _year_is_live(self, company_url: str) -> bool:
        """Discovery tests must not touch the network."""
        return True


def test_course_link_becomes_a_query_free_detail_url() -> None:
    client = _StubClient()

    courses = client._course_links(COMPANY_PAGE, "https://job.mynavi.jp/27")

    assert [course["url"] for course in courses] == [
        "https://job.mynavi.jp/27/pc/search/corp211619/recruiting_course27037949/"
        "recruiting_course.html",
        "https://job.mynavi.jp/27/pc/search/corp211619/recruiting_course27058549/"
        "recruiting_course.html",
    ]


def test_html_escaped_ampersand_in_a_course_link_still_parses() -> None:
    client = _StubClient()

    courses = client._course_links(COMPANY_PAGE, "https://job.mynavi.jp/27")

    assert "recruiting_course27058549" in courses[1]["url"]


def test_discovery_reads_the_sitemap_then_company_pages() -> None:
    client = _StubClient()

    jobs, failures = client.discover_detail_paths(max_jobs=2)

    assert failures == {}
    assert len(jobs) == 2
    assert all("/recruiting_course" in job["url"] for job in jobs)
    assert client.requested[0].endswith("_corp_employment.xml")
    assert any("/corp" in url and url.endswith("/employment.html") for url in client.requested)


def test_sitemap_ignores_outline_pages() -> None:
    client = _StubClient()

    companies = client._sitemap_companies(2027)

    assert companies == [
        "https://job.mynavi.jp/27/pc/search/corp2/employment.html",
        "https://job.mynavi.jp/27/pc/search/corp211619/employment.html",
    ]


# --- The 2028 sitemap is published before its cycle opens ---------------------

SITEMAP_2028 = """<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://job.mynavi.jp/28/pc/search/corp232085/employment.html</loc></url>
</urlset>
"""


class _CyclesOpeningStub(_StubClient):
    """Serves a 2028 sitemap whose company pages redirect; 2027 is live."""

    def _get(self, url: str) -> str:
        self.requested.append(url)
        if url.endswith("_2028_corp_employment.xml"):
            return SITEMAP_2028
        if url.endswith(".xml"):
            return SITEMAP
        return COMPANY_PAGE

    def _year_is_live(self, company_url: str) -> bool:
        return "/28/" not in company_url


def test_sitemap_for_a_cycle_that_has_not_opened_is_skipped() -> None:
    client = _CyclesOpeningStub()

    prefix, companies = client._company_pages()

    assert prefix == "https://job.mynavi.jp/27"
    assert all("/27/" in company for company in companies)

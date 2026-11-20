"""Unit tests for the Chiletrabajos (Chile) scraper.

No network and no database: every test drives the pure mapping helpers or a
synthetic page built from the shapes measured in the site's archived markup
(2026-05 .. 2026-11). The fixtures are constructed here, not copied from the
archive, so the tests describe the contract rather than one capture.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from job_market_intel.scrapers.chiletrabajos_cl import (
    ChiletrabajosClClient,
    ChiletrabajosClSettings,
)
from job_market_intel.scrapers.chiletrabajos_cl.exceptions import (
    ChiletrabajosClFetchError,
    ChiletrabajosClParseError,
    ChiletrabajosClResponseError,
)
from job_market_intel.scrapers.chiletrabajos_cl.models import (
    RawChiletrabajosJob,
    SitemapEntry,
)
from job_market_intel.scrapers.chiletrabajos_cl.parser import (
    ChiletrabajosClParser,
    build_location,
    extract_job_posting,
    map_employment_type,
    map_region_code,
    normalize_description,
    parse_date,
    parse_salary,
    parse_salary_amount,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1570000", 1570000.0),
        (1570000, 1570000.0),
        ("1.570.000", 1570000.0),
        ("1,570,000", 1570000.0),
        ("1.570,50", 1570.5),
        ("0", None),
        (0, None),
        ("", None),
        (None, None),
        ("—", None),
        (True, None),
    ],
)
def test_parse_salary_amount(raw: object, expected: float | None) -> None:
    assert parse_salary_amount(raw) == expected


def test_parse_salary_reads_capital_value_key() -> None:
    salary = {
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "CLP",
            "value": {"@type": "QuantitativeValue", "Value": "1570000", "unitText": "MONTH"},
        }
    }
    assert parse_salary(salary) == (1570000.0, None, "CLP", "monthly", True)


def test_parse_salary_treats_zero_as_undisclosed() -> None:
    salary = {
        "baseSalary": {
            "currency": "CLP",
            "value": {"@type": "QuantitativeValue", "Value": 0, "unitText": "MONTH"},
        }
    }
    assert parse_salary(salary) == (None, None, "CLP", "monthly", False)


def test_parse_salary_reads_a_range_and_period() -> None:
    salary = {
        "baseSalary": {
            "currency": "CLP",
            "value": {"minValue": "800000", "maxValue": "1000000", "unitText": "YEAR"},
        }
    }
    assert parse_salary(salary) == (800000.0, 1000000.0, "CLP", "yearly", True)


def test_parse_salary_handles_absent_block() -> None:
    assert parse_salary({}) == (None, None, "CLP", "monthly", False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FULL_TIME", "full_time"),
        ("PART_TIME", "part_time"),
        ("CONTRACTOR", "contract"),
        ("TEMPORARY", "temporary"),
        ("INTERN", "internship"),
        (["PART_TIME"], "part_time"),
        ("part_time", "part_time"),
        ("PART_TIME, FULL_TIME", None),
        ("VOLUNTEER", None),
        ("OTHER", None),
        ("", None),
        (None, None),
    ],
)
def test_map_employment_type(raw: object, expected: str | None) -> None:
    assert map_employment_type(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AT", "Atacama"),
        ("at", "Atacama"),
        ("CL-AT", "Atacama"),
        ("RM", "Metropolitana de Santiago"),
        ("BI", "Biobío"),
        ("LL", "Los Lagos"),
        ("LI", "O'Higgins"),
        ("AN", "Antofagasta"),
        ("NB", "Ñuble"),
        ("XX", None),
        ("", None),
        (None, None),
        ("Región de Valparaíso", "Región de Valparaíso"),
    ],
)
def test_map_region_code(raw: object, expected: str | None) -> None:
    assert map_region_code(raw) == expected


def test_build_location_composes_city_region_and_country() -> None:
    location, parts = build_location(
        {"addressLocality": "Copiapó", "addressRegion": "AT", "addressCountry": "CL"}
    )
    assert location == "Copiapó; Atacama; CL"
    assert parts["country_iso2"] == "CL"


def test_build_location_handles_country_name_and_missing_city() -> None:
    assert build_location({"addressRegion": "RM", "addressCountry": "Chile"})[0] == (
        "Metropolitana de Santiago; CL"
    )
    assert build_location({"addressCountry": "Chile"})[0] == "CL"
    assert build_location({})[0] == "CL"


def test_build_location_reads_dict_shaped_address_parts() -> None:
    address = {
        "addressLocality": {"@type": "City", "name": "Santiago"},
        "addressRegion": {"@type": "AdministrativeArea", "name": "RM"},
        "addressCountry": {"@type": "Country", "name": "Chile"},
    }
    assert build_location(address)[0] == "Santiago; Metropolitana de Santiago; CL"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-08 16:20:42", datetime(2026, 10, 8, 16, 20, 42)),
        ("2026-12-22T16:20:42", datetime(2026, 12, 22, 16, 20, 42)),
        ("2026-12-22T16:20:42Z", datetime(2026, 12, 22, 16, 20, 42)),
        ("2026-12-22", datetime(2026, 12, 22)),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(raw: object, expected: datetime | None) -> None:
    assert parse_date(raw) == expected


def test_normalize_description_decodes_entities_and_html() -> None:
    raw = (
        "Se requiere &quot;Personal Administrativo&quot;.\r\n\r\n"
        "<p>Experiencia: 3 a\u00f1os</p>\r\n<p>Correo: a@b.cl</p>"
    )
    text = normalize_description(raw)
    assert '"Personal Administrativo"' in text
    assert "Experiencia: 3 años" in text
    assert "<p>" not in text
    assert "\r" not in text
    assert normalize_description(None) == ""


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


def _job_posting(**overrides: object) -> dict:
    obj: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "CLP",
            "value": {"@type": "QuantitativeValue", "Value": "1570000", "unitText": "MONTH"},
        },
        "datePosted": "2026-10-08 16:20:42",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Selección Táctica",
            "logo": "",
        },
        "industry": "Otros",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Copiapó",
                "addressRegion": "AT",
                "addressCountry": "CL",
                "postalCode": 1530000,
            },
        },
        "employmentType": "FULL_TIME",
        "title": "07 Prevencionista de riesgos Copiapó",
        "description": (
            "¡Buscamos Ingeniero/a en Prevención de Riesgos!\r\n\r\n"
            "Ingeniero/a con registro de experto vigente.\r\n"
            "Mínimo 3 años de experiencia en minería."
        ),
        "validThrough": "2026-12-22T16:20:42",
    }
    obj.update(overrides)
    return obj


def _page(job_posting: dict | None = None, *, breadcrumb_first: bool = True) -> str:
    blocks = {
        "breadcrumb": {
            "@context": "http://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": 1}],
        },
        "job": job_posting if job_posting is not None else _job_posting(),
        "related": {"@context": "http://schema.org", "@type": "ItemList", "itemListElement": []},
    }
    order = (
        ("breadcrumb", "job", "related") if breadcrumb_first else ("related", "job", "breadcrumb")
    )
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(blocks[key], ensure_ascii=False)}</script>'
        for key in order
    )
    return f"<html><head>{scripts}</head><body><h1>Ad</h1></body></html>"


def test_extract_job_posting_skips_the_other_blocks() -> None:
    html = _page()
    from bs4 import BeautifulSoup

    posting = extract_job_posting(BeautifulSoup(html, "html.parser"))
    assert posting["@type"] == "JobPosting"
    assert posting["title"].startswith("07 Prevencionista")


def test_extract_job_posting_finds_a_graph_member() -> None:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "name": "Chiletrabajos"},
            _job_posting(title="Graph job"),
        ],
    }
    html = (
        f'<html><head><script type="application/ld+json">{json.dumps(graph)}</script></head></html>'
    )
    from bs4 import BeautifulSoup

    assert extract_job_posting(BeautifulSoup(html, "html.parser"))["title"] == "Graph job"


def _raw(html: str | None = None, **overrides: object) -> RawChiletrabajosJob:
    payload = {
        "job_id": "3911682",
        "url": "https://www.chiletrabajos.cl/trabajo/07-prevencionista-de-riesgos-copiapo-3911682",
        "sitemap_position": 0,
        "sitemap_total": 32993,
        "lastmod": "2026-10-09T03:29:15.281Z",
        "html_content": html if html is not None else _page(),
    }
    payload.update(overrides)
    return RawChiletrabajosJob(**payload)


# ---------------------------------------------------------------------------
# Ad-page parsing
# ---------------------------------------------------------------------------


def test_parse_job_maps_a_complete_page() -> None:
    job = ChiletrabajosClParser().parse_job(_raw())

    assert job.source_job_id == "3911682"
    assert job.job_title == "07 Prevencionista de riesgos Copiapó"
    assert job.company_name == "Selección Táctica"
    assert job.company_logo_url is None
    assert job.location_cleaned == "Copiapó; Atacama; CL"
    assert (job.salary_min, job.salary_max) == (1570000.0, None)
    assert job.salary_disclosed is True
    assert (job.currency_iso_code, job.pay_period) == ("CLP", "monthly")
    assert job.employment_type_code == "full_time"
    assert job.posting_date == datetime(2026, 10, 8, 16, 20, 42)
    assert job.closing_date == datetime(2026, 12, 22, 16, 20, 42)
    assert job.raw_payload["description_source"] == "json_ld.description"
    assert job.raw_payload["sitemap_position"] == 0
    assert job.raw_payload["postal_code"] == 1530000
    assert job.word_count > 5


def test_parse_job_treats_zero_salary_as_undisclosed() -> None:
    posting = _job_posting(
        baseSalary={
            "currency": "CLP",
            "value": {"@type": "QuantitativeValue", "Value": 0, "unitText": "MONTH"},
        }
    )
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))
    assert job.salary_disclosed is False
    assert job.salary_min is None and job.salary_max is None


def test_parse_job_keeps_multi_valued_employment_as_unknown() -> None:
    posting = _job_posting(employmentType="PART_TIME, FULL_TIME")
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))
    assert job.employment_type_code is None
    assert job.raw_payload["employment_type_raw"] == "PART_TIME, FULL_TIME"


def test_parse_job_falls_back_to_confidential_employer_and_summary() -> None:
    posting = _job_posting(
        hiringOrganization={"@type": "Organization", "name": "", "logo": ""},
        description="",
    )
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))

    assert job.company_name == "Confidential Employer"
    assert job.raw_payload["description_source"] == "structured_summary"
    assert "Oferta de empleo publicada en Chiletrabajos." in (job.description_clean or "")
    assert job.data_quality_score <= 0.6


def test_parse_job_reads_telecommute_marker() -> None:
    posting = _job_posting(jobLocationType="TELECOMMUTE")
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))
    assert job.remote_work_type_code == "remote_country"


def test_parse_job_does_not_infer_remote_from_prose() -> None:
    posting = _job_posting(description="Trabajo 100% remoto desde casa.")
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))
    assert job.remote_work_type_code is None


def test_parse_job_drops_a_closing_date_before_the_posting_date() -> None:
    posting = _job_posting(datePosted="2026-12-01 10:00:00", validThrough="2026-11-01T10:00:00")
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))
    assert job.closing_date is None


def test_parse_job_uses_the_page_title_when_the_block_has_none() -> None:
    posting = _job_posting(title="")
    job = ChiletrabajosClParser().parse_job(_raw(_page(posting)))
    assert job.job_title == "Ad"


def test_parse_job_rejects_a_page_with_no_title_anywhere() -> None:
    with pytest.raises(ChiletrabajosClParseError):
        ChiletrabajosClParser().parse_job(_raw("<html><body>no title</body></html>"))


def test_parse_job_rejects_a_missing_page() -> None:
    with pytest.raises(ChiletrabajosClParseError):
        ChiletrabajosClParser().parse_job(_raw(None, html_content=None))


def test_parse_jobs_skips_bad_pages_and_keeps_good_ones() -> None:
    good = _raw()
    bad = _raw(None, job_id="0", html_content="<html></html>")
    jobs = ChiletrabajosClParser().parse_jobs([good, bad])
    assert [job.source_job_id for job in jobs] == ["3911682"]


# ---------------------------------------------------------------------------
# Sitemap and window selection
# ---------------------------------------------------------------------------


def _sitemap(*slugs: str) -> str:
    urls = "".join(
        "<url><loc><![CDATA[https://www.chiletrabajos.cl/trabajo/"
        f"{slug}]]></loc><lastmod>2026-10-09T03:29:15.281Z</lastmod></url>"
        for slug in slugs
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )


def test_parse_sitemap_reads_job_entries_in_order() -> None:
    entries = ChiletrabajosClClient.parse_sitemap(
        _sitemap("chofer-3911905", "cocinero-3911904", "administrativo-3830784")
    )
    assert [entry.job_id for entry in entries] == ["3911905", "3911904", "3830784"]
    assert entries[0].position == 0
    assert entries[0].lastmod == "2026-10-09T03:29:15.281Z"


def test_parse_sitemap_skips_non_job_urls() -> None:
    xml = _sitemap("real-3911905").replace(
        "</urlset>",
        "<url><loc>https://www.chiletrabajos.cl/trabajos/otro</loc></url>"
        "<url><loc>https://www.chiletrabajos.cl/trabajo/sin-id</loc></url>"
        "</urlset>",
    )
    entries = ChiletrabajosClClient.parse_sitemap(xml)
    assert [entry.job_id for entry in entries] == ["3911905"]


def test_parse_sitemap_rejects_a_sitemapindex() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>"
    )
    with pytest.raises(ChiletrabajosClResponseError):
        ChiletrabajosClClient.parse_sitemap(xml)


def test_parse_sitemap_rejects_empty_and_malformed_input() -> None:
    with pytest.raises(ChiletrabajosClResponseError):
        ChiletrabajosClClient.parse_sitemap("")
    with pytest.raises(ChiletrabajosClResponseError):
        ChiletrabajosClClient.parse_sitemap("<urlset><url>")


def _entries(n: int) -> list[SitemapEntry]:
    return [
        SitemapEntry(
            job_id=str(3911905 - i),
            url=f"https://www.chiletrabajos.cl/trabajo/job-{3911905 - i}",
            lastmod="2026-10-09T03:29:15.281Z",
            position=i,
        )
        for i in range(n)
    ]


def test_select_window_takes_fresh_rows_then_the_pinned_tail() -> None:
    client = ChiletrabajosClClient(
        ChiletrabajosClSettings(fresh_rows=2, start_offset=5, inter_request_delay_seconds=0)
    )
    # fresh_rows=2 -> positions 0,1; the tail starts at position 2, so a
    # pinned start_offset of 5 is tail index 5 = position 7.
    selected = client.select_window(_entries(10), budget=4)
    assert [entry.position for entry in selected] == [0, 1, 7, 8]


def test_select_window_returns_everything_when_the_budget_covers_it() -> None:
    client = ChiletrabajosClClient(
        ChiletrabajosClSettings(fresh_rows=2, inter_request_delay_seconds=0)
    )
    selected = client.select_window(_entries(3), budget=10)
    assert [entry.position for entry in selected] == [0, 1, 2]


def test_rotation_offset_advances_with_the_calendar() -> None:
    client = ChiletrabajosClClient(ChiletrabajosClSettings(inter_request_delay_seconds=0))
    first = client.rotation_offset(100, 10)
    assert 0 <= first < 100


# ---------------------------------------------------------------------------
# Client orchestration (no network)
# ---------------------------------------------------------------------------


class _FakeClient(ChiletrabajosClClient):
    """Serves a synthetic sitemap and synthetic ad pages."""

    def __init__(self, entries: list[SitemapEntry], pages: dict[str, str], **settings: object):
        super().__init__(ChiletrabajosClSettings(**settings))
        self._entries = entries
        self._pages = pages
        self.detail_urls: list[str] = []

    def fetch_sitemap(self) -> str:  # type: ignore[override]
        return "<urlset/>"

    def parse_sitemap(self, xml: str) -> list[SitemapEntry]:  # type: ignore[override]
        return self._entries

    def fetch_detail(self, url: str) -> str:  # type: ignore[override]
        self.detail_urls.append(url)
        return self._pages[url]


def test_fetch_raw_jobs_selects_and_fetches_pages() -> None:
    entries = _entries(5)
    pages = {entry.url: _page() for entry in entries}
    client = _FakeClient(
        entries, pages, fresh_rows=2, start_offset=0, inter_request_delay_seconds=0
    )

    records, failures, total = client.fetch_raw_jobs(max_jobs=3)

    assert total == 5
    assert failures == {}
    assert [record.sitemap_position for record in records] == [0, 1, 2]
    assert len(client.detail_urls) == 3


def test_fetch_raw_jobs_records_a_failed_page_and_skips_it() -> None:
    entries = _entries(3)
    pages = {entry.url: _page() for entry in entries}

    class _Flaky(_FakeClient):
        def fetch_detail(self, url: str) -> str:  # type: ignore[override]
            if url.endswith("3911904"):
                raise ChiletrabajosClFetchError("HTTP 500")
            return super().fetch_detail(url)

    client = _Flaky(entries, pages, fresh_rows=3, start_offset=0, inter_request_delay_seconds=0)
    records, failures, total = client.fetch_raw_jobs(max_jobs=3)

    assert total == 3
    assert len(failures) == 1
    assert [record.job_id for record in records] == ["3911905", "3911903"]


def test_fetch_raw_jobs_raises_on_an_empty_sitemap() -> None:
    client = _FakeClient([], {}, inter_request_delay_seconds=0)
    with pytest.raises(ChiletrabajosClResponseError):
        client.fetch_raw_jobs(max_jobs=10)


def test_fetch_raw_jobs_with_a_non_positive_budget_is_a_no_op() -> None:
    client = _FakeClient(_entries(2), {}, inter_request_delay_seconds=0)
    assert client.fetch_raw_jobs(max_jobs=0) == ([], {}, 0)

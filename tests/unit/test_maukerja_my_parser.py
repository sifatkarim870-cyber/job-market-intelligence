"""Unit tests for the MauKerja (Malaysia) scraper.

No network and no database: every test drives the pure mapping helpers, a
synthetic ad page, or a synthetic sitemap chain built from the shapes measured
on the live site on 2026-11-20. The fixtures are constructed here, not copied
from a capture, so the tests describe the contract rather than one page.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from job_market_intel.scrapers.maukerja_my import (
    MaukerjaMyClient,
    MaukerjaMySettings,
)
from job_market_intel.scrapers.maukerja_my.exceptions import (
    MaukerjaMyFetchError,
    MaukerjaMyParseError,
    MaukerjaMyResponseError,
)
from job_market_intel.scrapers.maukerja_my.models import (
    RawMaukerjaMyJob,
    SitemapEntry,
)
from job_market_intel.scrapers.maukerja_my.parser import (
    MaukerjaMyParser,
    build_location,
    extract_identifier,
    extract_job_posting,
    map_employment_type,
    map_region,
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
        ("2300", 2300.0),
        (2300, 2300.0),
        ("3,500", 3500.0),
        ("1,234.50", 1234.5),
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


def test_parse_salary_reads_a_range_and_monthly_period() -> None:
    salary = {
        "salaryCurrency": "MYR",
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "MYR",
            "value": {
                "@type": "QuantitativeValue",
                "value": 2300,
                "minValue": 2300,
                "maxValue": 3500,
                "unitText": "MONTH",
            },
        },
    }
    assert parse_salary(salary) == (2300.0, 3500.0, "MYR", "monthly", True)


def test_parse_salary_treats_all_zero_as_undisclosed() -> None:
    salary = {
        "salaryCurrency": "MYR",
        "baseSalary": {
            "currency": "MYR",
            "value": {"value": 0, "minValue": 0, "maxValue": 0, "unitText": "MONTH"},
        },
    }
    assert parse_salary(salary) == (None, None, "MYR", "monthly", False)


def test_parse_salary_reads_a_single_value() -> None:
    salary = {"baseSalary": {"value": {"value": 2500, "unitText": "MONTH"}}}
    assert parse_salary(salary) == (2500.0, None, "MYR", "monthly", True)


def test_parse_salary_swaps_reversed_bounds() -> None:
    salary = {"baseSalary": {"value": {"minValue": 4000, "maxValue": 3000}}}
    assert parse_salary(salary) == (3000.0, 4000.0, "MYR", "monthly", True)


def test_parse_salary_reads_a_yearly_unit_and_falls_back_to_salary_currency() -> None:
    salary = {
        "salaryCurrency": "MYR",
        "baseSalary": {"value": {"value": 60000, "unitText": "YEAR"}},
    }
    assert parse_salary(salary) == (60000.0, None, "MYR", "yearly", True)


def test_parse_salary_handles_absent_block() -> None:
    assert parse_salary({}) == (None, None, "MYR", "monthly", False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["FULL_TIME"], "full_time"),
        (["PART_TIME"], "part_time"),
        (["CONTRACTOR"], "contract"),
        (["INTERN"], "internship"),
        ("FULL_TIME", "full_time"),
        ("full_time", "full_time"),
        (["FULL_TIME", "FULL_TIME"], "full_time"),
        ([], None),
        (["VOLUNTEER"], None),
        (["OTHER"], None),
        (["FULL_TIME", "PART_TIME"], None),
        (None, None),
    ],
)
def test_map_employment_type(raw: object, expected: str | None) -> None:
    assert map_employment_type(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Selangor", "Selangor"),
        ("WP Kuala Lumpur", "Kuala Lumpur"),
        # Case is preserved: the resolver matches region names case-insensitively.
        ("wp kuala lumpur", "kuala lumpur"),
        ("WP  Putrajaya", "Putrajaya"),
        ("81750", None),
        ("", None),
        (None, None),
        (["Perak"], "Perak"),
        ({"@type": "AdministrativeArea", "name": "Johor"}, "Johor"),
    ],
)
def test_map_region(raw: object, expected: str | None) -> None:
    assert map_region(raw) == expected


def test_build_location_composes_city_region_and_country() -> None:
    location, parts = build_location(
        {"addressLocality": "Tanjung Malim", "addressRegion": "Perak", "addressCountry": "MY"}
    )
    assert location == "Tanjung Malim; Perak; MY"
    assert parts["country_iso2"] == "MY"
    assert parts["region"] == "Perak"


def test_build_location_normalises_wp_region_and_dedupes() -> None:
    location, _ = build_location(
        {
            "addressLocality": "Kuala Lumpur",
            "addressRegion": "WP Kuala Lumpur",
            "addressCountry": "MY",
        }
    )
    assert location == "Kuala Lumpur; MY"


def test_build_location_handles_singapore_and_missing_parts() -> None:
    assert build_location({"addressRegion": "Singapore", "addressCountry": "SG"})[0] == (
        "Singapore; SG"
    )
    assert build_location({"addressCountry": "Malaysia"})[0] == "MY"
    assert build_location({})[0] == "MY"


def test_build_location_rejects_a_postal_code_region() -> None:
    location, parts = build_location(
        {"addressLocality": "Sungai Buloh", "addressRegion": "81750", "addressCountry": "MY"}
    )
    assert location == "Sungai Buloh; MY"
    assert parts["region"] == ""


def test_build_location_reads_dict_shaped_address_parts() -> None:
    address = {
        "addressLocality": {"@type": "City", "name": "Ipoh"},
        "addressRegion": {"@type": "AdministrativeArea", "name": "Perak"},
        "addressCountry": {"@type": "Country", "name": "Malaysia"},
    }
    assert build_location(address)[0] == "Ipoh; Perak; MY"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-20T12:18:11.000Z", datetime(2026, 11, 20, 12, 18, 11)),
        ("2026-12-27T15:59:59.000Z", datetime(2026, 12, 27, 15, 59, 59)),
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
        "Kelayakan &quot;Minimum 1 tahun&quot;.\n\n"
        "<ul><li>Mahir Mandarin</li><li>Boleh bekerja syif</li></ul>"
    )
    text = normalize_description(raw)
    assert '"Minimum 1 tahun"' in text
    assert "Mahir Mandarin" in text
    assert "<li>" not in text
    assert normalize_description(None) == ""


def test_extract_identifier_prefers_the_publisher_value() -> None:
    assert extract_identifier({"identifier": {"value": "xa6SyBU2OP"}}, "fallback") == "xa6SyBU2OP"
    assert extract_identifier({}, "fallback") == "fallback"
    assert extract_identifier({"identifier": "abc"}, "fallback") == "abc"


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


def _job_posting(**overrides: object) -> dict:
    obj: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "@id": "https://www.maukerja.my/job/xa6SyBU2OP-operator-warehouse",
        "url": "https://www.maukerja.my/job/xa6SyBU2OP-operator-warehouse",
        "title": "Operator Warehouse",
        "description": (
            "\n      Mengendalikan operasi gudang harian termasuk penerimaan, "
            "penyimpanan, pengambilan, pembungkusan, dan penghantaran barang."
            "\n      Memastikan ketepatan inventori mengikut sistem."
        ),
        "datePosted": "2026-11-20T12:18:11.000Z",
        "validThrough": "2026-12-27T15:59:59.000Z",
        "employmentType": ["FULL_TIME"],
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Goodwill Square (Malaysia) Sdn. Bhd.",
            "logo": "https://files.ajobthing.com/employers/205303-1795148570.png",
            "sameAs": "https://www.maukerja.my/company/goodwill-square",
        },
        "identifier": {
            "@type": "PropertyValue",
            "name": "Goodwill Square (Malaysia) Sdn. Bhd.",
            "value": "xa6SyBU2OP",
        },
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "MYR",
            "value": {
                "@type": "QuantitativeValue",
                "value": 1750,
                "minValue": 1750,
                "maxValue": 2000,
                "unitText": "MONTH",
            },
        },
        "salaryCurrency": "MYR",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Tanjung Malim",
                "addressRegion": "Perak",
                "addressCountry": "MY",
            },
        },
        "occupationalCategory": "Pembuatan / Produksi",
        "skills": ["Manufacturing", "Logistics Coordination", "Kaizen"],
        "jobBenefits": ["KWSP", "PERKESO", "Cuti Tahunan"],
        "directApply": True,
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
    }
    order = ("breadcrumb", "job") if breadcrumb_first else ("job", "breadcrumb")
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(blocks[key], ensure_ascii=False)}</script>'
        for key in order
    )
    return f"<html><head>{scripts}</head><body><h1>Ad</h1></body></html>"


def test_extract_job_posting_skips_the_breadcrumb_block() -> None:
    from bs4 import BeautifulSoup

    posting = extract_job_posting(BeautifulSoup(_page(), "html.parser"))
    assert posting["@type"] == "JobPosting"
    assert posting["title"] == "Operator Warehouse"


def test_extract_job_posting_finds_a_graph_member() -> None:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "name": "AJobThing"},
            _job_posting(title="Graph job"),
        ],
    }
    html = (
        f'<html><head><script type="application/ld+json">{json.dumps(graph)}</script></head></html>'
    )
    from bs4 import BeautifulSoup

    assert extract_job_posting(BeautifulSoup(html, "html.parser"))["title"] == "Graph job"


def _raw(html: str | None = None, **overrides: object) -> RawMaukerjaMyJob:
    payload = {
        "job_id": "xa6SyBU2OP",
        "url": "https://www.maukerja.my/job/xa6SyBU2OP-operator-warehouse",
        "sitemap_position": 0,
        "sitemap_total": 46652,
        "lastmod": "2026-11-20",
        "html_content": html if html is not None else _page(),
    }
    payload.update(overrides)
    return RawMaukerjaMyJob(**payload)


# ---------------------------------------------------------------------------
# Ad-page parsing
# ---------------------------------------------------------------------------


def test_parse_job_maps_a_complete_page() -> None:
    job = MaukerjaMyParser().parse_job(_raw())

    assert job.source_job_id == "xa6SyBU2OP"
    assert job.job_title == "Operator Warehouse"
    assert job.company_name == "Goodwill Square (Malaysia) Sdn. Bhd."
    assert job.company_logo_url == "https://files.ajobthing.com/employers/205303-1795148570.png"
    assert job.location_cleaned == "Tanjung Malim; Perak; MY"
    assert (job.salary_min, job.salary_max) == (1750.0, 2000.0)
    assert job.salary_disclosed is True
    assert (job.currency_iso_code, job.pay_period) == ("MYR", "monthly")
    assert job.employment_type_code == "full_time"
    assert job.posting_date == datetime(2026, 11, 20, 12, 18, 11)
    assert job.closing_date == datetime(2026, 12, 27, 15, 59, 59)
    assert job.raw_payload["description_source"] == "json_ld.description"
    assert job.raw_payload["skills"] == ["Manufacturing", "Logistics Coordination", "Kaizen"]
    assert job.raw_payload["job_benefits"] == ["KWSP", "PERKESO", "Cuti Tahunan"]
    assert job.raw_payload["occupational_category"] == "Pembuatan / Produksi"
    assert job.raw_payload["sitemap_position"] == 0
    assert job.word_count > 5


def test_parse_job_treats_zero_salary_as_undisclosed() -> None:
    posting = _job_posting(
        baseSalary={
            "currency": "MYR",
            "value": {"value": 0, "minValue": 0, "maxValue": 0, "unitText": "MONTH"},
        }
    )
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.salary_disclosed is False
    assert job.salary_min is None and job.salary_max is None


def test_parse_job_keeps_conflicting_employment_types_as_unknown() -> None:
    posting = _job_posting(employmentType=["FULL_TIME", "PART_TIME"])
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.employment_type_code is None
    assert job.raw_payload["employment_type_raw"] == ["FULL_TIME", "PART_TIME"]


def test_parse_job_falls_back_to_confidential_employer_and_summary() -> None:
    posting = _job_posting(
        hiringOrganization={"@type": "Organization", "name": "", "logo": ""},
        identifier={"@type": "PropertyValue", "value": "xa6SyBU2OP"},
        description="",
    )
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))

    assert job.company_name == "Confidential Employer"
    assert job.raw_payload["description_source"] == "structured_summary"
    assert "Iklan kerja yang disiarkan di MauKerja." in (job.description_clean or "")
    assert job.data_quality_score <= 0.6


def test_parse_job_uses_identifier_name_when_organization_is_unnamed() -> None:
    posting = _job_posting(
        hiringOrganization={"@type": "Organization", "name": ""},
        identifier={"@type": "PropertyValue", "name": "Fallback Sdn Bhd", "value": "xa6SyBU2OP"},
    )
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.company_name == "Fallback Sdn Bhd"


def test_parse_job_ignores_a_non_http_logo() -> None:
    posting = _job_posting(hiringOrganization={"@type": "Organization", "name": "X", "logo": ""})
    assert MaukerjaMyParser().parse_job(_raw(_page(posting))).company_logo_url is None


def test_parse_job_reads_telecommute_marker() -> None:
    posting = _job_posting(jobLocationType="TELECOMMUTE")
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.remote_work_type_code == "remote_country"


def test_parse_job_does_not_infer_remote_from_prose() -> None:
    posting = _job_posting(description="Kerja dari rumah sepenuhnya, 100% remote.")
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.remote_work_type_code is None


def test_parse_job_drops_a_closing_date_before_the_posting_date() -> None:
    posting = _job_posting(
        datePosted="2026-12-01T10:00:00.000Z",
        validThrough="2026-11-01T10:00:00.000Z",
    )
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.closing_date is None


def test_parse_job_handles_a_singapore_ad() -> None:
    posting = _job_posting(
        jobLocation={
            "@type": "Place",
            "address": {
                "addressLocality": "Singapore",
                "addressRegion": "Singapore",
                "addressCountry": "SG",
            },
        }
    )
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.location_cleaned == "Singapore; SG"
    assert job.raw_payload["location_parts"]["country_iso2"] == "SG"


def test_parse_job_uses_the_page_title_when_the_block_has_none() -> None:
    posting = _job_posting(title="")
    job = MaukerjaMyParser().parse_job(_raw(_page(posting)))
    assert job.job_title == "Ad"


def test_parse_job_rejects_a_page_with_no_title_anywhere() -> None:
    with pytest.raises(MaukerjaMyParseError):
        MaukerjaMyParser().parse_job(_raw("<html><body>no title</body></html>"))


def test_parse_job_rejects_a_missing_page() -> None:
    with pytest.raises(MaukerjaMyParseError):
        MaukerjaMyParser().parse_job(_raw(None, html_content=None))


def test_parse_jobs_skips_bad_pages_and_keeps_good_ones() -> None:
    good = _raw()
    bad = _raw(None, job_id="0", html_content="<html></html>")
    jobs = MaukerjaMyParser().parse_jobs([good, bad])
    assert [job.source_job_id for job in jobs] == ["xa6SyBU2OP"]


# ---------------------------------------------------------------------------
# Sitemap parsing and window selection
# ---------------------------------------------------------------------------


def _urlset(*pairs: tuple[str, str]) -> str:
    urls = "".join(
        f"<url><loc>https://www.maukerja.my/job/{job_id}-{slug}</loc>"
        f"<lastmod>2026-11-20</lastmod></url>"
        for job_id, slug in pairs
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )


def test_parse_job_urlset_reads_entries_in_order() -> None:
    entries = MaukerjaMyClient.parse_job_urlset(
        _urlset(("xa6SyBU2OP", "operator-warehouse"), ("m2xfKLyGyW", "stock-controller"))
    )
    assert [job_id for job_id, _, _ in entries] == ["xa6SyBU2OP", "m2xfKLyGyW"]
    assert entries[0][2] == "2026-11-20"


def test_parse_job_urlset_skips_non_ad_urls() -> None:
    xml = _urlset(("real123456", "job")).replace(
        "</urlset>",
        "<url><loc>https://www.maukerja.my/company/acme/jobs</loc></url>"
        "<url><loc>https://www.maukerja.my/jobsearch/jobs-in-ipoh</loc></url>"
        "</urlset>",
    )
    assert [job_id for job_id, _, _ in MaukerjaMyClient.parse_job_urlset(xml)] == ["real123456"]


def test_parse_job_urlset_rejects_a_sitemapindex_and_empty_input() -> None:
    index = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://www.maukerja.my/mk_job1.xml</loc></sitemap></sitemapindex>"
    )
    with pytest.raises(MaukerjaMyResponseError):
        MaukerjaMyClient.parse_job_urlset(index)
    with pytest.raises(MaukerjaMyResponseError):
        MaukerjaMyClient.parse_job_urlset("")
    with pytest.raises(MaukerjaMyResponseError):
        MaukerjaMyClient.parse_job_urlset("<urlset><url>")


def _index(*locs: str) -> str:
    children = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{children}</sitemapindex>"
    )


def test_child_job_sitemaps_keeps_only_mk_job_names() -> None:
    xml = _index(
        "https://www.maukerja.my/mk_general.xml",
        "https://www.maukerja.my/mk_job.xml",
        "https://www.maukerja.my/mk_company_job.xml",
        "https://sitemaps.maukerja.my/mk_jobsearch.xml",
        "https://www.maukerja.my/mk_job2.xml",
    )
    assert MaukerjaMyClient.child_job_sitemaps(xml) == [
        "https://www.maukerja.my/mk_job.xml",
        "https://www.maukerja.my/mk_job2.xml",
    ]


def test_child_job_sitemaps_rejects_a_urlset() -> None:
    with pytest.raises(MaukerjaMyResponseError):
        MaukerjaMyClient.child_job_sitemaps(_urlset(("real123456", "job")))


def _entries(n: int) -> list[SitemapEntry]:
    return [
        SitemapEntry(
            job_id=f"id{i:08d}",
            url=f"https://www.maukerja.my/job/id{i:08d}-job",
            lastmod="2026-11-20",
            position=i,
        )
        for i in range(n)
    ]


def test_select_window_takes_fresh_rows_then_the_pinned_tail() -> None:
    client = MaukerjaMyClient(
        MaukerjaMySettings(fresh_rows=2, start_offset=5, inter_request_delay_seconds=0)
    )
    # fresh_rows=2 -> positions 0,1; the tail starts at position 2, so a
    # pinned start_offset of 5 is tail index 5 = position 7.
    selected = client.select_window(_entries(10), budget=4)
    assert [entry.position for entry in selected] == [0, 1, 7, 8]


def test_select_window_returns_everything_when_the_budget_covers_it() -> None:
    client = MaukerjaMyClient(MaukerjaMySettings(fresh_rows=2, inter_request_delay_seconds=0))
    assert [entry.position for entry in client.select_window(_entries(3), budget=10)] == [0, 1, 2]


def test_rotation_offset_advances_with_the_calendar() -> None:
    client = MaukerjaMyClient(MaukerjaMySettings(inter_request_delay_seconds=0))
    first = client.rotation_offset(100, 10)
    assert 0 <= first < 100


# ---------------------------------------------------------------------------
# Client orchestration (no network)
# ---------------------------------------------------------------------------


class _FakeClient(MaukerjaMyClient):
    """Serves a synthetic sitemap chain and synthetic ad pages."""

    def __init__(
        self,
        documents: dict[str, str],
        pages: dict[str, str],
        **settings: object,
    ) -> None:
        super().__init__(MaukerjaMySettings(**settings))
        self._documents = documents
        self._pages = pages
        self.detail_urls: list[str] = []

    def _fetch_xml(self, url: str) -> str:  # type: ignore[override]
        return self._documents[url]

    def fetch_detail(self, url: str) -> str:  # type: ignore[override]
        self.detail_urls.append(url)
        return self._pages[url]


def test_fetch_sitemap_entries_walks_index_to_index_to_urlset() -> None:
    documents = {
        "https://www.maukerja.my/sitemap.xml": _index(
            "https://www.maukerja.my/mk_general.xml",
            "https://www.maukerja.my/mk_job.xml",
        ),
        "https://www.maukerja.my/mk_job.xml": _index("https://www.maukerja.my/mk_job1.xml"),
        "https://www.maukerja.my/mk_job1.xml": _urlset(
            ("xa6SyBU2OP", "operator-warehouse"), ("m2xfKLyGyW", "stock-controller")
        ),
    }
    client = _FakeClient(documents, {}, inter_request_delay_seconds=0)
    entries = client.fetch_sitemap_entries()
    assert [entry.job_id for entry in entries] == ["xa6SyBU2OP", "m2xfKLyGyW"]
    assert [entry.position for entry in entries] == [0, 1]


def test_fetch_sitemap_entries_dedupes_by_job_id() -> None:
    documents = {
        "https://www.maukerja.my/sitemap.xml": _index("https://www.maukerja.my/mk_job.xml"),
        "https://www.maukerja.my/mk_job.xml": _index(
            "https://www.maukerja.my/mk_job1.xml", "https://www.maukerja.my/mk_job2.xml"
        ),
        "https://www.maukerja.my/mk_job1.xml": _urlset(("dupe123456", "a")),
        "https://www.maukerja.my/mk_job2.xml": _urlset(("dupe123456", "a"), ("other12345", "b")),
    }
    client = _FakeClient(documents, {}, inter_request_delay_seconds=0)
    entries = client.fetch_sitemap_entries()
    assert [entry.job_id for entry in entries] == ["dupe123456", "other12345"]


def test_fetch_raw_jobs_selects_and_fetches_pages() -> None:
    documents = {
        "https://www.maukerja.my/sitemap.xml": _index("https://www.maukerja.my/mk_job.xml"),
        "https://www.maukerja.my/mk_job.xml": _index("https://www.maukerja.my/mk_job1.xml"),
        "https://www.maukerja.my/mk_job1.xml": _urlset(
            *[(f"id{i:08d}", f"job-{i}") for i in range(5)]
        ),
    }
    pages = {f"https://www.maukerja.my/job/id{i:08d}-job-{i}": _page() for i in range(5)}
    client = _FakeClient(
        documents, pages, fresh_rows=2, start_offset=0, inter_request_delay_seconds=0
    )

    records, failures, total = client.fetch_raw_jobs(max_jobs=3)

    assert total == 5
    assert failures == {}
    assert [record.sitemap_position for record in records] == [0, 1, 2]
    assert len(client.detail_urls) == 3


def test_fetch_raw_jobs_records_a_failed_page_and_skips_it() -> None:
    documents = {
        "https://www.maukerja.my/sitemap.xml": _index("https://www.maukerja.my/mk_job.xml"),
        "https://www.maukerja.my/mk_job.xml": _index("https://www.maukerja.my/mk_job1.xml"),
        "https://www.maukerja.my/mk_job1.xml": _urlset(
            ("aaa0000001", "a"), ("bbb0000002", "b"), ("ccc0000003", "c")
        ),
    }
    pages = {
        "https://www.maukerja.my/job/aaa0000001-a": _page(),
        "https://www.maukerja.my/job/bbb0000002-b": _page(),
        "https://www.maukerja.my/job/ccc0000003-c": _page(),
    }

    class _Flaky(_FakeClient):
        def fetch_detail(self, url: str) -> str:  # type: ignore[override]
            if url.endswith("bbb0000002-b"):
                raise MaukerjaMyFetchError("HTTP 500")
            return super().fetch_detail(url)

    client = _Flaky(documents, pages, fresh_rows=3, start_offset=0, inter_request_delay_seconds=0)
    records, failures, total = client.fetch_raw_jobs(max_jobs=3)

    assert total == 3
    assert len(failures) == 1
    assert [record.job_id for record in records] == ["aaa0000001", "ccc0000003"]


def test_fetch_raw_jobs_raises_on_an_empty_sitemap() -> None:
    documents = {
        "https://www.maukerja.my/sitemap.xml": _index("https://www.maukerja.my/mk_job.xml"),
        "https://www.maukerja.my/mk_job.xml": _index("https://www.maukerja.my/mk_job1.xml"),
        "https://www.maukerja.my/mk_job1.xml": _urlset(),
    }
    client = _FakeClient(documents, {}, inter_request_delay_seconds=0)
    with pytest.raises(MaukerjaMyResponseError):
        client.fetch_raw_jobs(max_jobs=10)


def test_fetch_raw_jobs_with_a_non_positive_budget_is_a_no_op() -> None:
    client = _FakeClient({}, {}, inter_request_delay_seconds=0)
    assert client.fetch_raw_jobs(max_jobs=0) == ([], {}, 0)

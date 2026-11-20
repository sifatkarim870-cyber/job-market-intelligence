"""Unit tests for the jobup.ch (Switzerland) scraper.

No network and no database: every test drives the pure mapping helpers, a
synthetic ad page, or a synthetic sitemap chain built from the shapes measured
on the live site on 2026-11-20. The fixtures are constructed here, not copied
from a capture, so the tests describe the contract rather than one page.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime

import pytest

from job_market_intel.scrapers.jobup_ch import (
    JobupChClient,
    JobupChSettings,
)
from job_market_intel.scrapers.jobup_ch.exceptions import (
    JobupChFetchError,
    JobupChParseError,
    JobupChResponseError,
)
from job_market_intel.scrapers.jobup_ch.models import (
    RawJobupChJob,
    SitemapEntry,
)
from job_market_intel.scrapers.jobup_ch.parser import (
    JobupChParser,
    _clean_locality,
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
        ("54231.34", 54231.34),
        (54231.34, 54231.34),
        ("1'234.50", 1234.5),
        ("5,420", 5420.0),
        ("0", None),
        (0, None),
        ("", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_salary_amount(raw: object, expected: float | None) -> None:
    assert parse_salary_amount(raw) == expected


def test_parse_salary_reads_a_yearly_range() -> None:
    block = {
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "CHF",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 54231.34,
                "maxValue": 94231.34,
                "unitText": "YEAR",
            },
        }
    }
    minimum, maximum, currency, period, disclosed = parse_salary(block)
    assert (minimum, maximum, currency, period, disclosed) == (
        54231.34,
        94231.34,
        "CHF",
        "yearly",
        True,
    )


def test_parse_salary_treats_an_empty_quantitative_value_as_undisclosed() -> None:
    block = {
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "CHF",
            "value": {"@type": "QuantitativeValue"},
        }
    }
    minimum, maximum, currency, period, disclosed = parse_salary(block)
    assert (minimum, maximum, currency, disclosed) == (None, None, "CHF", False)
    assert period == "monthly"


def test_parse_salary_reads_a_single_value() -> None:
    block = {"baseSalary": {"@type": "MonetaryAmount", "value": 6000, "currency": "CHF"}}
    minimum, maximum, _currency, _period, disclosed = parse_salary(block)
    assert (minimum, maximum, disclosed) == (6000.0, None, True)


def test_parse_salary_swaps_reversed_bounds() -> None:
    block = {
        "baseSalary": {
            "value": {"minValue": 90000, "maxValue": 60000, "unitText": "YEAR"},
            "currency": "CHF",
        }
    }
    minimum, maximum, _c, _p, _d = parse_salary(block)
    assert (minimum, maximum) == (60000.0, 90000.0)


def test_parse_salary_falls_back_to_salary_currency() -> None:
    block = {
        "salaryCurrency": "CHF",
        "baseSalary": {"value": {"minValue": 100, "maxValue": 200, "unitText": "HOUR"}},
    }
    minimum, maximum, currency, period, disclosed = parse_salary(block)
    assert (minimum, maximum, currency, period, disclosed) == (
        100.0,
        200.0,
        "CHF",
        "hourly",
        True,
    )


def test_parse_salary_handles_absent_block() -> None:
    assert parse_salary({}) == (None, None, "CHF", "monthly", False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["FULL_TIME"], "full_time"),
        (["PART_TIME"], "part_time"),
        (["FULL_TIME", "PART_TIME"], None),
        ("Permanent position", None),
        ("Temporary", "temporary"),
        ("Apprenticeship", "apprenticeship"),
        ("Internship", "internship"),
        ("Freelance", "freelance"),
        ("Contract", "contract"),
        ("part-time", "part_time"),
        (None, None),
        (["VOLUNTEER"], None),
    ],
)
def test_map_employment_type(raw: object, expected: str | None) -> None:
    assert map_employment_type(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Zürich", "Zürich"),
        ("Zurich", "Zürich"),
        ("Genève", "Genève"),
        ("Genf", "Genève"),
        ("Geneva", "Genève"),
        ("Niderwalden", "Nidwalden"),
        ("St. Gallen", "St. Gallen"),
        ("Region Basel", "Region Basel"),
        ("EMEA > CHE > Stabio", None),
        ("", None),
        (None, None),
    ],
)
def test_map_region(raw: object, expected: str | None) -> None:
    assert map_region(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Winterthur", "Winterthur"),
        ("Wetzikon ZH", "Wetzikon"),
        ("Lachen SZ (8853 Lachen)", "Lachen"),
        ("Haag (Rheintal) (9469 Buchs (SG))", "Haag"),
        ("Pfäffikon SZ (8808 Freienbach)", "Pfäffikon"),
        ("Ilanz - Via Crappa Grossa 24", "Ilanz"),
        ("Stadt Winterthur", "Winterthur"),
        ("EMEA > CHE > Stabio > VF Campus", ""),
        ("Je nach Baustelle im Oberwallis", ""),
        ("", ""),
    ],
)
def test_clean_locality(raw: object, expected: str) -> None:
    assert _clean_locality(raw) == expected


def test_build_location_composes_city_canton_and_country() -> None:
    location, parts = build_location(
        {"addressLocality": "Winterthur", "addressRegion": "Zürich", "addressCountry": "CH"}
    )
    assert location == "Winterthur; Zürich; CH"
    assert parts == {
        "city": "Winterthur",
        "region": "Zürich",
        "country_raw": "CH",
        "country_iso2": "CH",
    }


def test_build_location_dedupes_and_defaults_to_ch() -> None:
    location, parts = build_location({"addressLocality": "Genève", "addressRegion": "Genève"})
    assert location == "Genève; CH"
    assert parts["country_iso2"] == "CH"


def test_build_location_handles_missing_parts() -> None:
    location, parts = build_location({})
    assert location == "CH"
    assert parts["city"] == "" and parts["region"] == ""


def test_build_location_reads_dict_shaped_address_parts() -> None:
    location, _ = build_location(
        {
            "addressLocality": {"@type": "Text", "name": "Bern"},
            "addressRegion": {"@type": "Text", "name": "Bern"},
            "addressCountry": "CH",
        }
    )
    assert location == "Bern; CH"


def test_build_location_promotes_a_non_canton_region_to_a_city() -> None:
    location, parts = build_location({"addressRegion": "Le Mont-sur-Lausanne (VD)"})
    assert location == "Le Mont-sur-Lausanne; CH"
    assert parts["city"] == "Le Mont-sur-Lausanne"
    assert parts["region"] == ""


def test_build_location_keeps_a_real_canton_in_the_region_slot() -> None:
    location, parts = build_location({"addressRegion": "Vaud"})
    assert location == "Vaud; CH"
    assert parts["region"] == "Vaud"
    assert parts["city"] == ""


def test_build_location_prefers_locality_over_a_town_in_the_region_slot() -> None:
    location, parts = build_location(
        {"addressLocality": "Winterthur", "addressRegion": "Region Seeland"}
    )
    assert location == "Winterthur; Region Seeland; CH"
    assert parts["city"] == "Winterthur"
    assert parts["region"] == "Region Seeland"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-21T02:38:57+02:00", datetime(2026, 9, 21, 2, 38, 57)),
        ("2026-12-20T10:02:52.000Z", datetime(2026, 12, 20, 10, 2, 52)),
        ("2026-09-21", datetime(2026, 9, 21)),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(raw: object, expected: datetime | None) -> None:
    assert parse_date(raw) == expected


def test_normalize_description_decodes_entities_and_html() -> None:
    raw = "<div><p>Are numbers &amp; people your thing?</p><ul><li>Manage cash</li></ul></div>"
    text = normalize_description(raw)
    assert "numbers & people" in text
    assert "<" not in text
    assert "Manage cash" in text


def test_extract_identifier_prefers_the_publisher_value() -> None:
    block = {"identifier": {"@type": "PropertyValue", "value": "abc-123"}}
    assert extract_identifier(block, "fallback") == "abc-123"
    assert extract_identifier({}, "fallback") == "fallback"


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


def _job_posting(**overrides: object) -> dict:
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Finance Clerk 80-100 %",
        "description": "<p>Are numbers your strength? Join us as a Finance Assistant!</p>",
        "datePosted": "2026-09-21T02:38:57+02:00",
        "employmentType": ["PART_TIME", "FULL_TIME"],
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Stiftung Alters- und Pflegeheim Weggis",
        },
        "industry": "Healthcare",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Weggis",
                "postalCode": "6353",
                "addressCountry": "CH",
            },
        },
    }
    posting.update(overrides)
    return posting


def _page(job_posting: dict | None = None, *, breadcrumb_first: bool = True) -> str:
    posting = _job_posting() if job_posting is None else job_posting
    blocks = [
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [],
        },
        posting,
    ]
    if not breadcrumb_first:
        blocks.reverse()
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(block)}</script>' for block in blocks
    )
    return (
        "<html><head><title>Finance Clerk - Job offer on jobup.ch</title></head>"
        f"<body>{scripts}</body></html>"
    )


def test_extract_job_posting_skips_the_breadcrumb_block() -> None:
    soup = __import__("bs4").BeautifulSoup(_page(), "html.parser")
    posting = extract_job_posting(soup)
    assert posting["@type"] == "JobPosting"
    assert posting["title"] == "Finance Clerk 80-100 %"


def test_extract_job_posting_finds_a_graph_member() -> None:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "BreadcrumbList"},
            _job_posting(title="Graph Job"),
        ],
    }
    html = (
        '<html><body><script type="application/ld+json">'
        + json.dumps(graph)
        + "</script></body></html>"
    )
    soup = __import__("bs4").BeautifulSoup(html, "html.parser")
    assert extract_job_posting(soup)["title"] == "Graph Job"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _raw(html: str | None = None, **overrides: object) -> RawJobupChJob:
    fields = {
        "job_id": "a68ade13-8165-4776-8f51-245f32de63e1",
        "url": "https://www.jobup.ch/en/jobs/detail/a68ade13-8165-4776-8f51-245f32de63e1/",
        "sitemap_position": 0,
        "sitemap_total": 1,
        "html_content": _page() if html is None else html,
    }
    fields.update(overrides)
    return RawJobupChJob(**fields)


def test_parse_job_maps_a_complete_page() -> None:
    job = JobupChParser().parse_job(_raw())
    assert job.source_job_id == "a68ade13-8165-4776-8f51-245f32de63e1"
    assert job.job_title == "Finance Clerk 80-100 %"
    assert job.company_name == "Stiftung Alters- und Pflegeheim Weggis"
    assert job.location_cleaned == "Weggis; CH"
    assert job.employment_type_code is None  # two conflicting codes
    assert job.posting_date == datetime(2026, 9, 21, 2, 38, 57)
    assert job.currency_iso_code == "CHF"
    assert job.salary_disclosed is False
    assert job.word_count > 0
    assert job.data_quality_score <= 0.95


def test_parse_job_maps_a_single_employment_code() -> None:
    job = JobupChParser().parse_job(_raw(_page(_job_posting(employmentType=["FULL_TIME"]))))
    assert job.employment_type_code == "full_time"


def test_parse_job_maps_prose_employment_type() -> None:
    job = JobupChParser().parse_job(_raw(_page(_job_posting(employmentType="Temporary"))))
    assert job.employment_type_code == "temporary"


def test_parse_job_reads_a_salary_range() -> None:
    posting = _job_posting(
        baseSalary={
            "@type": "MonetaryAmount",
            "currency": "CHF",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 54231.34,
                "maxValue": 94231.34,
                "unitText": "YEAR",
            },
        }
    )
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.salary_min == 54231.34
    assert job.salary_max == 94231.34
    assert job.salary_disclosed is True
    assert job.pay_period == "yearly"
    assert job.currency_iso_code == "CHF"


def test_parse_job_ignores_an_empty_salary_block() -> None:
    posting = _job_posting(
        baseSalary={
            "@type": "MonetaryAmount",
            "currency": "CHF",
            "value": {"@type": "QuantitativeValue"},
        }
    )
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.salary_disclosed is False


def test_parse_job_normalises_a_canton_region() -> None:
    posting = _job_posting(
        jobLocation={
            "@type": "Place",
            "address": {"addressRegion": "Zürich", "addressCountry": "CH"},
        }
    )
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.location_cleaned == "Zürich; CH"


def test_parse_job_reads_telecommute_marker() -> None:
    posting = _job_posting(jobLocationType="TELECOMMUTE")
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.remote_work_type_code == "remote_country"


def test_parse_job_does_not_infer_remote_from_applicant_requirements() -> None:
    posting = _job_posting(
        applicantLocationRequirements={"@type": "Country", "name": "Switzerland"}
    )
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.remote_work_type_code is None


def test_parse_job_falls_back_to_confidential_employer() -> None:
    posting = _job_posting(hiringOrganization={})
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.company_name == "Confidential Employer"


def test_parse_job_ignores_a_non_http_logo() -> None:
    posting = _job_posting(hiringOrganization={"name": "ACME", "logo": "javascript:void(0)"})
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.company_logo_url is None


def test_parse_job_uses_the_page_title_when_the_block_has_none() -> None:
    posting = _job_posting(title="")
    job = JobupChParser().parse_job(_raw(_page(posting)))
    assert job.job_title == "Finance Clerk"


def test_parse_job_rejects_a_page_with_no_title_anywhere() -> None:
    html = "<html><head></head><body><p>nothing</p></body></html>"
    with pytest.raises(JobupChParseError):
        JobupChParser().parse_job(_raw(html))


def test_parse_job_rejects_a_missing_page() -> None:
    with pytest.raises(JobupChParseError):
        JobupChParser().parse_job(_raw(html="", html_content=None))


def test_parse_jobs_skips_bad_pages_and_keeps_good_ones() -> None:
    good = _raw()
    bad = _raw(html="<html></html>", job_id="dead")
    jobs = JobupChParser().parse_jobs([good, bad])
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "a68ade13-8165-4776-8f51-245f32de63e1"


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------


def _urlset(*pairs: tuple[str, str]) -> str:
    body = "".join(
        f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>" for loc, lastmod in pairs
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>"
    )


def test_parse_job_urlset_reads_entries_in_order() -> None:
    loc = "https://www.jobup.ch/en/jobs/detail/a68ade13-8165-4776-8f51-245f32de63e1/"
    xml = _urlset((loc, "2026-09-21T11:02:44+02:00"))
    entries = JobupChClient.parse_job_urlset(xml)
    assert entries == [("a68ade13-8165-4776-8f51-245f32de63e1", loc, "2026-09-21T11:02:44+02:00")]


def test_parse_job_urlset_skips_non_ad_urls() -> None:
    xml = _urlset(
        ("https://www.jobup.ch/en/company/acme/", "2026-09-21"),
        ("https://www.jobup.ch/en/jobs/detail/11111111-1111-1111-1111-111111111111/", "2026-09-22"),
    )
    entries = JobupChClient.parse_job_urlset(xml)
    assert len(entries) == 1
    assert entries[0][0] == "11111111-1111-1111-1111-111111111111"


def test_parse_job_urlset_rejects_a_sitemapindex_and_empty_input() -> None:
    index = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
    with pytest.raises(JobupChResponseError):
        JobupChClient.parse_job_urlset(index)
    with pytest.raises(JobupChResponseError):
        JobupChClient.parse_job_urlset("   ")


def _index(*locs: str) -> str:
    body = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + body
        + "</sitemapindex>"
    )


def test_child_job_sitemaps_keeps_only_job_paths() -> None:
    xml = _index(
        "https://www.jobup.ch/sitemaps/jobup/en/job/sitemap.job-en.xml.gz",
        "https://www.jobup.ch/sitemaps/jobup/en/company/sitemap.company_en.xml.gz",
        "https://www.jobup.ch/sitemaps/jobup/en/category/sitemap.category_en.xml.gz",
    )
    assert JobupChClient.child_job_sitemaps(xml) == [
        "https://www.jobup.ch/sitemaps/jobup/en/job/sitemap.job-en.xml.gz"
    ]


def test_child_job_sitemaps_rejects_a_urlset() -> None:
    with pytest.raises(JobupChResponseError):
        JobupChClient.child_job_sitemaps(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
        )


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------


def _entries(n: int) -> list[SitemapEntry]:
    return [
        SitemapEntry(job_id=f"job-{i}", url=f"https://e/{i}", lastmod="2026-11-20", position=i)
        for i in range(n)
    ]


def test_select_window_takes_fresh_rows_then_the_pinned_tail() -> None:
    client = JobupChClient(settings=JobupChSettings(fresh_rows=3, start_offset=0))
    chosen = client.select_window(_entries(10), budget=5)
    assert [e.job_id for e in chosen] == ["job-0", "job-1", "job-2", "job-3", "job-4"]


def test_select_window_returns_everything_when_the_budget_covers_it() -> None:
    client = JobupChClient(settings=JobupChSettings())
    entries = _entries(4)
    assert client.select_window(entries, budget=10) == entries


def test_rotation_offset_advances_with_the_calendar() -> None:
    pinned = JobupChClient(settings=JobupChSettings(start_offset=7))
    assert pinned.rotation_offset(100, 10) == 7
    unpinned = JobupChClient(settings=JobupChSettings())
    assert 0 <= unpinned.rotation_offset(100, 10) < 100


# ---------------------------------------------------------------------------
# Client (sitemap walk + fetch)
# ---------------------------------------------------------------------------


class _FakeClient(JobupChClient):
    """A client whose network calls are replaced by in-memory documents."""

    def __init__(self, documents: dict[str, str], pages: dict[str, str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._documents = documents
        self._pages = pages or {}

    def _fetch_xml(self, url: str) -> str:  # type: ignore[override]
        return self._documents[url]

    def fetch_detail(self, url: str) -> str:  # type: ignore[override]
        if url not in self._pages:
            raise JobupChFetchError(f"missing page {url}")
        return self._pages[url]


def _sitemap_fixture() -> tuple[dict[str, str], dict[str, str]]:
    jobmap = "https://www.jobup.ch/sitemaps/jobup/en/job/sitemap.job-en.xml.gz"
    index = "https://www.jobup.ch/sitemaps/jobup/en/sitemap.xml"
    old = "https://www.jobup.ch/en/jobs/detail/11111111-1111-1111-1111-111111111111/"
    new = "https://www.jobup.ch/en/jobs/detail/22222222-2222-2222-2222-222222222222/"
    documents = {
        index: _index(jobmap),
        jobmap: _urlset(
            (old, "2026-09-21T11:02:44+02:00"),
            (new, "2026-11-20T14:58:55+01:00"),
        ),
    }
    pages = {old: _page(_job_posting(title="Old Job")), new: _page(_job_posting(title="New Job"))}
    return documents, pages


def test_fetch_sitemap_entries_walks_index_to_urlset_newest_first() -> None:
    documents, _ = _sitemap_fixture()
    client = _FakeClient(documents)
    entries = client.fetch_sitemap_entries()
    # The sitemap is oldest-first; the client must sort newest-first.
    assert [e.job_id for e in entries] == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
    ]


def test_fetch_sitemap_entries_dedupes_by_job_id() -> None:
    index = "https://www.jobup.ch/sitemaps/jobup/en/sitemap.xml"
    jobmap = "https://www.jobup.ch/sitemaps/jobup/en/job/sitemap.job-en.xml.gz"
    loc = "https://www.jobup.ch/en/jobs/detail/11111111-1111-1111-1111-111111111111/"
    documents = {
        index: _index(jobmap),
        jobmap: _urlset((loc, "2026-09-21"), (loc, "2026-09-21")),
    }
    assert len(_FakeClient(documents).fetch_sitemap_entries()) == 1


def test_fetch_raw_jobs_selects_and_fetches_pages() -> None:
    documents, pages = _sitemap_fixture()
    client = _FakeClient(documents, pages, settings=JobupChSettings(max_jobs_per_run=10))
    records, failures, total = client.fetch_raw_jobs()
    assert total == 2
    assert len(records) == 2
    assert failures == {}
    assert all(record.html_content for record in records)


def test_fetch_raw_jobs_records_a_failed_page_and_skips_it() -> None:
    documents, pages = _sitemap_fixture()
    stale = "https://www.jobup.ch/en/jobs/detail/11111111-1111-1111-1111-111111111111/"
    pages.pop(stale)
    client = _FakeClient(documents, pages, settings=JobupChSettings(max_jobs_per_run=10))
    records, failures, total = client.fetch_raw_jobs()
    assert total == 2
    assert len(records) == 1
    assert stale in failures


def test_fetch_raw_jobs_raises_on_an_empty_sitemap() -> None:
    index = "https://www.jobup.ch/sitemaps/jobup/en/sitemap.xml"
    empty = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
    client = _FakeClient({index: empty})
    with pytest.raises(JobupChResponseError):
        client.fetch_raw_jobs()


def test_fetch_raw_jobs_with_a_non_positive_budget_is_a_no_op() -> None:
    documents, _ = _sitemap_fixture()
    client = _FakeClient(documents)
    records, failures, total = client.fetch_raw_jobs(max_jobs=0)
    assert (records, failures, total) == ([], {}, 0)


def test_fetch_xml_decompresses_gzip() -> None:
    class _Resp:
        content = gzip.compress(b"<urlset/>")
        encoding = "utf-8"

    client = JobupChClient()
    client._get = lambda url, timeout=None: _Resp()  # type: ignore[assignment]
    assert client._fetch_xml("https://example/x.xml.gz") == "<urlset/>"

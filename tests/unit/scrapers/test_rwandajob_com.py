"""Unit tests for the Rwandajob.com (Rwanda) scraper.

Pinned measured facts (2026-11-20, live site):

  * The search directory is ``/job-vacancies-search-rwanda``; page 1 has no
    query string and page N uses ``?page=N``.
  * The board held 116 offers over 5 pages (25 x 4 plus a final page of 16),
    with no URL overlap between pages.
  * Ad URLs live under ``/job-vacancies-rwanda/<slug>-<id>``.
  * Every sampled detail page carries a Schema.org ``JobPosting`` block whose
    ``identifier.value`` is the canonical ad id.
  * ``employmentType`` is often a multi-value string such as
    ``"Permanent contract - Fixed-term contract - Freelance"``.
  * ``jobLocation.address.addressCountry`` is the clean label ``Rwanda``.
  * ``jobLocation.address.addressRegion`` is NOT a region: it is the list of
    provinces the ad is open to (``"Eastern Province - Kigali Province - ..."``),
    so it must never be stored as a place.
  * 3 of a 9-ad sample needed the unescaped-quote JSON-LD repair
    (``<p align="left">`` inside ``description``).
  * ``baseSalary`` was absent on every sampled ad.

No test touches the network.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.scrapers.rwandajob_com import (
    RawRwandaJob,
    RwandaJobClient,
    RwandaJobParser,
    RwandaJobPipeline,
    RwandaJobResponseError,
    RwandaJobSettings,
    job_id_from_href,
)
from job_market_intel.scrapers.rwandajob_com.parser import (
    HOME_COUNTRY,
    build_location,
    detect_remote,
    extract_identifier,
    extract_json_ld,
    map_employment_type,
    normalize_country,
    parse_date,
)

_AD_PREFIX = "/job-vacancies-rwanda/"

LISTING_PAGE_0 = f"""<html><body>
<a href="{_AD_PREFIX}business-development-manager-kigali-184383">BDM</a>
<a href="/{_AD_PREFIX}pos-manager-kigali-184559">POS</a>
<a href="/job-vacancies-search-rwanda?page=1">2</a>
<a href="https://www.emploibenin.com">Benin</a>
</body></html>"""

LISTING_PAGE_1 = f"""<html><body>
<a href="{_AD_PREFIX}pos-manager-kigali-184559">POS</a>
<a href="{_AD_PREFIX}iot-embedded-systems-engineer-kigali-185690">IoT</a>
</body></html>"""

#: The live ads put every province they are open to into ``addressRegion``.
_REGION = " - ".join(
    [
        "Eastern Province",
        "Kigali Province",
        "Northern Province",
        "Southern Province",
        "Western Province",
        "International",
    ]
)

DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-20T15:55:02+02:00",
  "title": "Business Development Manager - Kigali",
  "identifier": {"@type": "PropertyValue", "name": "BRISK MARKETING LTD.", "value": "184383"},
  "validThrough": "2026-11-21T10:48:14+02:00",
  "employmentType": "Permanent contract",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "BRISK MARKETING LTD.",
    "logo": "https://www.rwandajob.com/sites/rwandajob.com/files/logo/brisk.png"
  },
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Kigali",
    "addressRegion": "__REGION__",
    "addressCountry": "Rwanda"
  }},
  "description": "<p>We are seeking a Business Development Manager to join our team.</p>"
}
</script>
<script type="application/ld+json">
{"@context": "http://schema.org", "@type": "WebSite", "name": "Rwandajob.com",}
</script>
</head><body>
<h1>Business Development Manager - Kigali</h1>
<h3>BRISK MARKETING LTD.</h3>
<div class="job-description">
  We are seeking a Business Development Manager to lead commercial strategy.
  The role covers revenue growth, key partnerships, client acquisition and
  monthly reporting. Python and Excel are useful for the dashboards; the
  successful candidate has strong sales and management experience.
</div>
</body></html>""".replace("__REGION__", _REGION)

#: The live defect: unescaped double quotes inside the JSON-LD description.
BROKEN_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-10-01T09:00:00+02:00",
  "title": "Cloud System Integrator (M/F) - Kigali",
  "description": "<p align="left">We are looking for a Cloud System Integrator.</p>
<p align="left"><strong>Missions</strong></p>",
  "identifier": {"@type": "PropertyValue", "name": "TANGO ENTERPRISES", "value": "99005"},
  "validThrough": "2027-03-31T23:59:00+02:00",
  "employmentType": "Fixed-term contract",
  "hiringOrganization": {"@type": "Organization", "name": "TANGO ENTERPRISES"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Kigali",
    "addressRegion": "Kigali Province",
    "addressCountry": "Rwanda"
  }}
}
</script>
</head><body>
<h1>Cloud System Integrator (M/F) - Kigali</h1>
<h3>TANGO ENTERPRISES</h3>
<div class="job-description">We are looking for a Cloud System Integrator to
design and operate cloud platforms for a regional client.</div>
</body></html>"""

#: No JSON-LD at all: the HTML fallback must still produce a row.
NO_JSONLD = """<!DOCTYPE html><body>
<h1>Warehouse Assistant Manager</h1>
<h3>RWANOVA GROUP</h3>
<div class="job-description">We are recruiting a Warehouse Assistant Manager for Kigali.</div>
</body></html>"""

AGENT_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-18T08:12:00+02:00",
  "title": "Digital Marketer - Kigali",
  "identifier": {"@type": "PropertyValue", "name": "SOLAR CHEF BV", "value": "185107"},
  "validThrough": "2026-11-28T12:22:49+02:00",
  "employmentType": "Fixed-term contract - Freelance - Part-time work",
  "hiringOrganization": {"@type": "Organization", "name": "SOLAR CHEF BV"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Kigali",
    "addressRegion": "Kigali Province",
    "addressCountry": "Rwanda"
  }}
}
</script>
</head><body>
<h1>Digital Marketer - Kigali</h1>
<h3>SOLAR CHEF BV</h3>
<div class="job-description">Digital marketing for Kigali. Part time possible.</div>
</body></html>"""

REMOTE_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-09-29T11:37:03+02:00",
  "title": "Network Architect (M/F)",
  "identifier": {"@type": "PropertyValue", "name": "TANGO ENTERPRISES", "value": "99009"},
  "validThrough": "2027-03-31T23:59:00+02:00",
  "employmentType": "Permanent contract",
  "hiringOrganization": {"@type": "Organization", "name": "TANGO ENTERPRISES"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "/ Travail a Distance",
    "addressRegion": "Kigali Province - International",
    "addressCountry": "Rwanda"
  }}
}
</script>
</head><body>
<h1>Network Architect (M/F)</h1>
<h3>TANGO ENTERPRISES</h3>
<div class="job-description">Remote network architecture role open worldwide.</div>
</body></html>"""


def _raw(html: str = DETAIL, job_id: str = "business-development-manager-kigali-184383"):
    return RawRwandaJob(
        url=f"https://www.rwandajob.com/job-vacancies-rwanda/{job_id}",
        job_id=job_id,
        html_content=html,
    )


class TestJobIdFromHref:
    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            ("/job-vacancies-rwanda/business-development-manager-kigali-184383", "184383"),
            (
                "https://www.rwandajob.com/job-vacancies-rwanda/pos-manager-kigali-184559",
                "184559",
            ),
            ("/job-vacancies-rwanda/iot-embedded-systems-engineer-kigali-185690/", "185690"),
            ("/job-vacancies-rwanda/iot-embedded-systems-engineer-kigali-185690?x=1", "185690"),
            ("/job-vacancies-rwanda/no-numeric-id", "no-numeric-id"),
            ("/job-vacancies-search-rwanda?page=1", None),
            ("https://www.emploibenin.com", None),
            ("", None),
        ],
    )
    def test_discovery_id(self, href, expected):
        assert job_id_from_href(href) == expected


class TestListingUrl:
    def test_page_one_has_no_query_string(self):
        client = RwandaJobClient(RwandaJobSettings(rate_limit_delay=0))
        assert client.listing_url(0) == "https://www.rwandajob.com/job-vacancies-search-rwanda"
        assert client.listing_url(1) == (
            "https://www.rwandajob.com/job-vacancies-search-rwanda?page=1"
        )
        assert client.listing_url(4) == (
            "https://www.rwandajob.com/job-vacancies-search-rwanda?page=4"
        )


class TestDiscovery:
    def test_ads_are_deduped_and_sibling_country_links_ignored(self):
        client = RwandaJobClient(RwandaJobSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else LISTING_PAGE_1
        found, pages_scraped = client.discover_job_urls(max_pages=3)
        assert pages_scraped == 3
        ids = {discovery_id for _, discovery_id in found}
        assert ids == {"184383", "184559", "185690"}

    def test_a_page_with_no_new_links_stops_discovery(self):
        client = RwandaJobClient(RwandaJobSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else "<html></html>"
        found, pages_scraped = client.discover_job_urls(max_pages=5)
        assert len(found) == 2
        assert pages_scraped == 2

    def test_an_empty_board_raises_rather_than_returning_nothing(self):
        client = RwandaJobClient(RwandaJobSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: "<html><body></body></html>"
        with pytest.raises(RwandaJobResponseError, match="markup changed"):
            client.discover_job_urls(max_pages=2)

    def test_fetch_job_urls_applies_the_budget(self):
        client = RwandaJobClient(
            RwandaJobSettings(rate_limit_delay=0, max_jobs_per_run=2, fresh_rows=2)
        )
        client.discover_job_urls = lambda max_pages=None: (
            [("u0", "0"), ("u1", "1"), ("u2", "2")],
            3,
        )
        selected, pages = client.fetch_job_urls()
        assert [jid for _, jid in selected] == ["0", "1"]
        assert pages == 3


class TestWindow:
    def _items(self, n: int) -> list[tuple[str, str]]:
        return [(f"u{i}", f"{i:04d}") for i in range(n)]

    def test_a_budget_above_the_board_takes_everything(self):
        client = RwandaJobClient(RwandaJobSettings(rate_limit_delay=0))
        assert client.select_window(self._items(5), 10) == self._items(5)

    def test_the_newest_rows_are_always_taken(self):
        client = RwandaJobClient(
            RwandaJobSettings(rate_limit_delay=0, fresh_rows=3, start_offset=0)
        )
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0002", "0003", "0004"]

    def test_the_tail_window_rotates(self):
        client = RwandaJobClient(
            RwandaJobSettings(rate_limit_delay=0, fresh_rows=2, start_offset=4)
        )
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0006", "0007", "0008"]

    def test_the_window_wraps_around_the_tail(self):
        client = RwandaJobClient(
            RwandaJobSettings(rate_limit_delay=0, fresh_rows=0, start_offset=8)
        )
        chosen = client.select_window(self._items(10), 4)
        assert [jid for _, jid in chosen] == ["0008", "0009", "0000", "0001"]

    def test_the_offset_advances_one_window_per_day(self):
        client = RwandaJobClient(RwandaJobSettings(rate_limit_delay=0, fresh_rows=0))
        today = date.today().toordinal()
        assert client.rotation_offset(1000, 90) == (today * 90) % 1000


class TestEmploymentType:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Permanent contract", "full_time"),
            ("Fixed-term contract", "temporary"),
            ("Temporary work", "temporary"),
            ("Internship", "internship"),
            ("Part-time work", "part_time"),
            ("Freelance", "freelance"),
            ("Permanent contract - Fixed-term contract", None),
            ("Fixed-term contract - Freelance - Part-time work", None),
            ("Permanent contract - Fixed-term contract - Freelance", None),
            (["Internship", "Intern"], "internship"),
            (["Internship", "Freelance"], None),
            ("", None),
            (None, None),
        ],
    )
    def test_mapping(self, value, expected):
        assert map_employment_type(value) == expected


class TestCountryAndLocation:
    def test_board_country_label_is_normalized(self):
        assert normalize_country("Rwanda") == HOME_COUNTRY
        assert normalize_country("RW") == HOME_COUNTRY
        assert normalize_country("RWA") == HOME_COUNTRY
        assert normalize_country("Kenya") == "Kenya"

    def test_a_normal_address_keeps_the_city_and_country(self):
        location = build_location(
            {
                "addressLocality": "Kigali",
                "addressRegion": _REGION,
                "addressCountry": "Rwanda",
            },
            "on_site",
        )
        assert location == f"Kigali, {HOME_COUNTRY}"
        assert "Province" not in location, "the province list is not a region"

    def test_a_country_only_locality_is_not_repeated(self):
        location = build_location(
            {
                "addressLocality": "Rwanda",
                "addressRegion": "Kigali Province",
                "addressCountry": "Rwanda",
            },
            "on_site",
        )
        assert location == HOME_COUNTRY

    def test_an_identical_city_and_region_is_not_repeated(self):
        location = build_location(
            {
                "addressLocality": "Kigali",
                "addressRegion": "Kigali",
                "addressCountry": "Rwanda",
            },
            "on_site",
        )
        assert location == f"Kigali, {HOME_COUNTRY}"

    def test_a_remote_ad_does_not_keep_the_province_list(self):
        location = build_location(
            {
                "addressLocality": "/ Travail a Distance",
                "addressRegion": "Kigali Province - International",
                "addressCountry": "Rwanda",
            },
            "remote_global",
        )
        assert location == f"Remote, {HOME_COUNTRY}"

    def test_a_missing_country_falls_back_to_rwanda(self):
        location = build_location({"addressLocality": "Kigali"}, "on_site")
        assert location == f"Kigali, {HOME_COUNTRY}"

    @pytest.mark.parametrize(
        ("title", "locality", "region", "expected"),
        [
            ("Engineer", "Kigali", "Kigali Province", "on_site"),
            ("Engineer", "Kigali", "Kigali Province - International", "on_site"),
            ("Engineer", "/ Travail a Distance", "Kigali Province", "remote_country"),
            (
                "Engineer",
                "/ Travail a Distance",
                "Kigali Province - International",
                "remote_global",
            ),
            ("Remote Engineer", "Kigali", "Kigali Province", "remote_country"),
            ("Anywhere Engineer", "Anywhere", "International", "remote_global"),
            (None, None, None, "on_site"),
        ],
    )
    def test_remote_detection(self, title, locality, region, expected):
        assert detect_remote(title, locality, region) == expected


class TestDatesAndIdentifier:
    def test_iso_date(self):
        assert parse_date("2026-11-20T15:55:02+02:00") == datetime(2026, 11, 20)

    @pytest.mark.parametrize("value", ["20.11.2026", "20/11/2026"])
    def test_day_first_date(self, value):
        assert parse_date(value) == datetime(2026, 11, 20)

    @pytest.mark.parametrize("value", [None, "", "TBD", "31/02/2026"])
    def test_unreadable_dates_are_none(self, value):
        assert parse_date(value) is None

    def test_identifier_value_wins_over_the_discovery_id(self):
        assert extract_identifier({"identifier": {"value": "184383"}}, "slug") == "184383"
        assert extract_identifier({"identifier": "99005"}, "slug") == "99005"
        assert extract_identifier({}, "slug") == "slug"


class TestJsonLd:
    def test_a_valid_block_with_raw_newlines_is_read(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"].startswith("Business Development")
        assert data["identifier"]["value"] == "184383"

    def test_unescaped_quotes_in_the_description_are_repaired(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(BROKEN_DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"] == "Cloud System Integrator (M/F) - Kigali"
        assert data["identifier"]["value"] == "99005"
        assert data["employmentType"] == "Fixed-term contract"


class TestParser:
    def test_the_contract_is_fully_populated(self):
        job = RwandaJobParser().parse_job(_raw())
        assert job.source_job_id == "184383"
        assert job.job_title.startswith("Business Development")
        assert job.company_name == "BRISK MARKETING LTD."
        assert job.company_logo_url == (
            "https://www.rwandajob.com/sites/rwandajob.com/files/logo/brisk.png"
        )
        assert job.location_cleaned == f"Kigali, {HOME_COUNTRY}"
        assert job.posting_date == datetime(2026, 11, 20)
        assert job.closing_date == datetime(2026, 11, 21)
        assert job.employment_type_code == "full_time"
        assert job.remote_work_type_code == "on_site"
        assert job.currency_iso_code == "RWF"
        assert job.pay_period == "monthly"
        assert job.description_clean and "commercial" in job.description_clean
        assert job.word_count > 20

    def test_no_salary_is_invented(self):
        job = RwandaJobParser().parse_job(_raw())
        assert job.salary_min is None and job.salary_max is None
        assert job.salary_disclosed is False

    def test_the_province_list_is_not_in_the_clean_location(self):
        job = RwandaJobParser().parse_job(_raw())
        assert "Province" not in job.location_cleaned
        assert "International" not in job.location_cleaned

    def test_the_broken_jsonld_ad_still_parses(self):
        job = RwandaJobParser().parse_job(_raw(BROKEN_DETAIL, "cloud-system-integrator-mf-99005"))
        assert job.source_job_id == "99005"
        assert job.job_title == "Cloud System Integrator (M/F) - Kigali"
        assert job.company_name == "TANGO ENTERPRISES"
        assert job.employment_type_code == "temporary"
        assert job.description_clean and "Cloud System Integrator" in job.description_clean

    def test_html_fallback_when_jsonld_is_absent(self):
        job = RwandaJobParser().parse_job(_raw(NO_JSONLD, "warehouse-assistant-manager"))
        assert job.source_job_id == "warehouse-assistant-manager"
        assert job.job_title == "Warehouse Assistant Manager"
        assert job.company_name == "RWANOVA GROUP"
        assert job.location_cleaned == HOME_COUNTRY
        assert job.description_clean and "Warehouse" in job.description_clean
        assert job.employment_type_code is None

    def test_a_remote_ad_is_marked_remote_and_not_given_a_province_list(self):
        job = RwandaJobParser().parse_job(_raw(REMOTE_DETAIL, "network-architect-mf-99009"))
        assert job.source_job_id == "99009"
        assert job.remote_work_type_code == "remote_global"
        assert job.location_cleaned == f"Remote, {HOME_COUNTRY}"
        assert job.employment_type_code == "full_time"

    def test_a_multi_value_employment_type_is_ambiguous(self):
        job = RwandaJobParser().parse_job(_raw(AGENT_DETAIL, "digital-marketer-kigali-185107"))
        assert job.source_job_id == "185107"
        assert job.job_title == "Digital Marketer - Kigali"
        assert job.employment_type_code is None, (
            '"Fixed-term contract - Freelance - Part-time work" is three values'
        )
        assert (
            job.raw_payload["employment_type_raw"]
            == "Fixed-term contract - Freelance - Part-time work"
        )

    def test_html_entities_in_titles_are_decoded(self):
        html = DETAIL.replace(
            "Business Development Manager - Kigali",
            "Sales Engineer &#8211; Building Materials",
        )
        job = RwandaJobParser().parse_job(_raw(html, "assistant"))
        assert "\u2013" in job.job_title

    def test_a_closing_date_before_the_posting_is_dropped(self):
        html = DETAIL.replace("2026-11-21T10:48:14+02:00", "2026-11-01T00:00:00+02:00")
        job = RwandaJobParser().parse_job(_raw(html))
        assert job.closing_date is None

    def test_a_missing_posting_date_falls_back_to_the_visible_line(self):
        html = DETAIL.replace('"datePosted": "2026-11-20T15:55:02+02:00",', "")
        html = html.replace("<h1>", "<p>Published on 19.11.2026</p><h1>", 1)
        job = RwandaJobParser().parse_job(_raw(html))
        assert job.posting_date == datetime(2026, 11, 19)

    def test_no_description_is_none_not_the_title(self):
        html = NO_JSONLD.replace(
            '<div class="job-description">We are recruiting a Warehouse Assistant '
            "Manager for Kigali.</div>",
            "",
        )
        job = RwandaJobParser().parse_job(_raw(html, "warehouse-assistant-manager"))
        assert job.description_clean is None
        assert job.word_count == 0

    def test_a_page_without_a_title_is_skipped_not_invented(self):
        raw = _raw("<html><body><p>nothing</p></body></html>", "bad")
        assert RwandaJobParser().parse_jobs([raw]) == []

    def test_one_bad_page_does_not_drop_the_good_ones(self):
        good = _raw()
        bad = _raw("<html><body><p>nothing</p></body></html>", "bad")
        jobs = RwandaJobParser().parse_jobs([good, bad])
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "184383"

    def test_skills_are_extracted_from_the_description(self):
        job = RwandaJobParser().parse_job(_raw())
        assert "Python" in job.skills
        assert "Excel" in job.skills


class TestPipelineDryRun:
    class _Client:
        def __init__(self, targets, raws, pages=5):
            self.targets = targets
            self.raws = raws
            self.pages = pages

        def fetch_job_urls(self, max_jobs=None):
            return self.targets, self.pages

        def fetch_all_details(self, targets):
            return self.raws

    def test_a_dry_run_parses_without_persisting(self):
        client = self._Client(
            [("https://www.rwandajob.com/job-vacancies-rwanda/ad-184383", "x")],
            [_raw()],
            pages=5,
        )
        result = RwandaJobPipeline(
            settings=RwandaJobSettings(rate_limit_delay=0), client=client
        ).run(store_db=False)
        assert result.pages_scraped == 5
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 0
        assert result.failed_count == 0

    def test_zero_discovered_postings_is_reported(self):
        client = self._Client([], [], pages=1)
        result = RwandaJobPipeline(
            settings=RwandaJobSettings(rate_limit_delay=0), client=client
        ).run(store_db=False)
        assert result.validation_passed is False
        assert result.parsed_count == 0
        assert any("Zero job items" in issue for issue in result.issues)

    def test_zero_parsed_postings_fails_validation(self):
        client = self._Client(
            [("https://www.rwandajob.com/job-vacancies-rwanda/ad", "x")],
            [_raw("<html></html>", "bad")],
        )
        result = RwandaJobPipeline(
            settings=RwandaJobSettings(rate_limit_delay=0), client=client
        ).run(store_db=False)
        assert result.validation_passed is False
        assert any("Zero jobs successfully parsed" in issue for issue in result.issues)

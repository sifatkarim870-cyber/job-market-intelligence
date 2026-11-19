"""Unit tests for the Emploi.cd (DR Congo) scraper.

Pinned measured facts (2026-11-20, live site):

  * The search directory is ``/recherche-jobs-congo-rdc``; page 1 has no
    query string and page N uses ``?page=N``.
  * The board held 90 offers over 4 pages (24, 25, 25, 15 ad links), 89
    unique URLs, with no overlap between pages.
  * Ad URLs live under
    ``/offre-emploi-rdc-republique-democratique-congo/<slug>``; some slugs
    end in the numeric ad id and some do not.
  * Every good detail page carries a Schema.org ``JobPosting`` block whose
    ``identifier.value`` is the canonical ad id.
  * ``employmentType`` is often the multi-value
    ``"CDI - CDD - Intérim - Freelance"``.
  * One sampled ad's JSON-LD contains ``<p align="left">`` inside
    ``description`` -- the same unescaped-quote defect Emploi.ci has.
  * ``baseSalary`` was absent on every sampled ad.

No test touches the network.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.scrapers.emploi_cd import (
    EmploiCdClient,
    EmploiCdParser,
    EmploiCdPipeline,
    EmploiCdResponseError,
    EmploiCdSettings,
    RawEmploiCdJob,
    job_id_from_href,
)
from job_market_intel.scrapers.emploi_cd.parser import (
    HOME_COUNTRY,
    build_location,
    detect_remote,
    extract_identifier,
    extract_json_ld,
    map_employment_type,
    normalize_country,
    parse_date,
)

_CD_AD_PREFIX = "/offre-emploi-rdc-republique-democratique-congo/"

LISTING_PAGE_0 = f"""<html><body>
<a href="{_CD_AD_PREFIX}business-development-lead-beni-butembo-goma-bunia">Lead</a>
<a href="{_CD_AD_PREFIX}apporteur-affaires-independants-kinshasa-505848">Apporteur</a>
<a href="/recherche-jobs-congo-rdc?page=1">2</a>
<a href="https://www.emploi.cm">Cameroun</a>
</body></html>"""

LISTING_PAGE_1 = f"""<html><body>
<a href="{_CD_AD_PREFIX}apporteur-affaires-independants-kinshasa-505848">Apporteur</a>
<a href="{_CD_AD_PREFIX}consultant-sap-senior-hf-296562">SAP</a>
</body></html>"""

#: The live remote ads put every Congolese city into ``addressRegion``. Kept as
#: a real long value (assembled here so no source line is unreadably wide).
_REMOTE_REGION = " - ".join(
    [
        "Boende",
        "Bukavu",
        "Bunia",
        "Buta",
        "Gbadolite",
        "Gemena",
        "Goma",
        "Inongo",
        "Isiro",
        "Kabinda",
        "Kalemie",
        "Kamina",
        "Kananga",
        "Kenge",
        "Kikwit",
        "Kindu",
        "Kinshasa",
        "Kisangani",
        "Kolwezi",
        "Lisala",
        "Lodja",
        "Lubumbashi",
        "Luebo",
        "Matadi",
        "Mbandaka",
        "Mbuji-Mayi",
        "International",
    ]
)

DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-19T01:00:02+00:00",
  "title": "Business Development Lead - Beni/Butembo/Goma/Bunia",
  "identifier": {"@type": "PropertyValue", "name": "AFRICAWORK", "value": "515161"},
  "validThrough": "2027-01-06T00:00:00+00:00",
  "employmentType": "CDI - CDD - Int\\u00e9rim - Freelance",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICAWORK"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Kinshasa",
    "addressRegion": "Kinshasa",
    "addressCountry": "RDC - R\\u00e9publique D\\u00e9mocratique du Congo"
  }},
  "baseSalary": null,
  "description": "<p>We are searching for a Business Development Lead.</p>"
}
</script>
<script type="application/ld+json">
{"@context": "http://schema.org", "@type": "WebSite", "name": "Emploi.cd",}
</script>
</head><body>
<h1>Business Development Lead - Beni/Butembo/Goma/Bunia</h1>
<h3>AFRICAWORK</h3>
<div class="job-description">
  We are searching for a Business Development Lead for our client, a logistics
  solutions company in Africa. The role covers missions, reporting, and the
  management of a small team. Python and Excel are useful. Send your CV.
</div>
</body></html>"""

#: The live defect: unescaped double quotes inside the JSON-LD description.
BROKEN_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-18T13:55:01+00:00",
  "title": "Responsable Transit (H/F) - Kinshasa",
  "description": "<p align="left">Nous sommes à la recherche d'un Responsable Transit.</p>
<p align="left"><strong>Missions</strong></p>",
  "identifier": {"@type": "PropertyValue", "name": "CFAO RDC", "value": "506522"},
  "validThrough": "2026-12-11T16:15:41+00:00",
  "employmentType": "CDI",
  "hiringOrganization": {"@type": "Organization", "name": "CFAO RDC"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Kinshasa",
    "addressRegion": "Kinshasa",
    "addressCountry": "RDC - République Démocratique du Congo"
  }}
}
</script>
</head><body>
<h1>Responsable Transit (H/F) - Kinshasa</h1>
<h3>CFAO RDC</h3>
<div class="job-description">Nous sommes à la recherche d'un Responsable Transit.
Missions : superviser les opérations de transit et de dédouanement.</div>
</body></html>"""

#: No JSON-LD at all: the HTML fallback must still produce a row.
NO_JSONLD = """<!DOCTYPE html><html><body>
<h1>Chauffeur Livreur</h1>
<h3>TRANSPORT KIN SARL</h3>
<div class="job-description">Nous recherchons un chauffeur livreur pour Kinshasa.</div>
</body></html>"""

REMOTE_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-09-29T09:32:40+00:00",
  "title": "Consultant SAP Senior (H/F)",
  "identifier": {"@type": "PropertyValue", "name": "AFRICASHORE", "value": "296562"},
  "validThrough": "2027-03-31T23:59:00+00:00",
  "employmentType": "CDI - Freelance",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICASHORE"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "/ Travail En Remote",
    "addressRegion": "__REMOTE_REGION__",
    "addressCountry": "RDC - République Démocratique du Congo"
  }}
}
</script>
</head><body>
<h1>Consultant SAP Senior (H/F)</h1>
<h3>AFRICASHORE</h3>
<div class="job-description">Nous recherchons un Consultant SAP Sénior (H/F).</div>
</body></html>""".replace("__REMOTE_REGION__", _REMOTE_REGION)


def _raw(html: str = DETAIL, job_id: str = "business-development-lead-beni-butembo-goma-bunia"):
    return RawEmploiCdJob(
        url=f"https://www.emploi.cd/offre-emploi-rdc-republique-democratique-congo/{job_id}",
        job_id=job_id,
        html_content=html,
    )


class TestJobIdFromHref:
    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            (
                "/offre-emploi-rdc-republique-democratique-congo/apporteur-affaires-505848",
                "505848",
            ),
            (
                "https://www.emploi.cd/offre-emploi-rdc-republique-democratique-congo/"
                "business-development-lead-beni-butembo-goma-bunia",
                "business-development-lead-beni-butembo-goma-bunia",
            ),
            (
                "/offre-emploi-rdc-republique-democratique-congo/consultant-sap-senior-hf-296562/",
                "296562",
            ),
            (
                "/offre-emploi-rdc-republique-democratique-congo/consultant-sap-senior-hf-296562?x=1",
                "296562",
            ),
            ("/recherche-jobs-congo-rdc?page=1", None),
            ("https://www.emploi.cm", None),
            ("", None),
        ],
    )
    def test_discovery_id(self, href, expected):
        assert job_id_from_href(href) == expected


class TestListingUrl:
    def test_page_one_has_no_query_string(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0))
        assert client.listing_url(0) == "https://www.emploi.cd/recherche-jobs-congo-rdc"
        assert client.listing_url(1) == ("https://www.emploi.cd/recherche-jobs-congo-rdc?page=1")
        assert client.listing_url(3) == ("https://www.emploi.cd/recherche-jobs-congo-rdc?page=3")


class TestDiscovery:
    def test_ads_are_deduped_and_sibling_country_links_ignored(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else LISTING_PAGE_1
        found, pages_scraped = client.discover_job_urls(max_pages=3)
        assert pages_scraped == 3
        ids = {discovery_id for _, discovery_id in found}
        assert ids == {
            "business-development-lead-beni-butembo-goma-bunia",
            "505848",
            "296562",
        }

    def test_a_page_with_no_new_links_stops_discovery(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else "<html></html>"
        found, pages_scraped = client.discover_job_urls(max_pages=5)
        assert len(found) == 2
        assert pages_scraped == 2

    def test_an_empty_board_raises_rather_than_returning_nothing(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: "<html><body></body></html>"
        with pytest.raises(EmploiCdResponseError, match="markup changed"):
            client.discover_job_urls(max_pages=2)

    def test_fetch_job_urls_applies_the_budget(self):
        client = EmploiCdClient(
            EmploiCdSettings(rate_limit_delay=0, max_jobs_per_run=2, fresh_rows=2)
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
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0))
        assert client.select_window(self._items(5), 10) == self._items(5)

    def test_the_newest_rows_are_always_taken(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0, fresh_rows=3, start_offset=0))
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0002", "0003", "0004"]

    def test_the_tail_window_rotates(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0, fresh_rows=2, start_offset=4))
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0006", "0007", "0008"]

    def test_the_window_wraps_around_the_tail(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0, fresh_rows=0, start_offset=8))
        chosen = client.select_window(self._items(10), 4)
        assert [jid for _, jid in chosen] == ["0008", "0009", "0000", "0001"]

    def test_the_offset_advances_one_window_per_day(self):
        client = EmploiCdClient(EmploiCdSettings(rate_limit_delay=0, fresh_rows=0))
        today = date.today().toordinal()
        assert client.rotation_offset(1000, 90) == (today * 90) % 1000


class TestEmploymentType:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("CDI", "full_time"),
            ("CDD", "temporary"),
            ("Freelance", "freelance"),
            ("Stage", "internship"),
            ("Temps partiel", "part_time"),
            ("CDI - CDD - Intérim - Freelance", None),
            ("CDI - Freelance", None),
            (["CDI", "CDD"], None),
            (["CDI", "Permanent"], "full_time"),
            ("", None),
            (None, None),
        ],
    )
    def test_mapping(self, value, expected):
        assert map_employment_type(value) == expected


class TestCountryAndLocation:
    def test_board_country_label_is_normalized(self):
        assert normalize_country("RDC - République Démocratique du Congo") == HOME_COUNTRY
        assert normalize_country("CD") == HOME_COUNTRY
        assert normalize_country("France") == "France"

    def test_a_normal_address_keeps_city_region_and_country(self):
        location = build_location(
            {
                "addressLocality": "Lubumbashi",
                "addressRegion": "Haut-Katanga",
                "addressCountry": "RDC - République Démocratique du Congo",
            },
            "on_site",
        )
        assert location == f"Lubumbashi, Haut-Katanga, {HOME_COUNTRY}"

    def test_an_identical_city_and_region_is_not_repeated(self):
        location = build_location(
            {
                "addressLocality": "Kinshasa",
                "addressRegion": "Kinshasa",
                "addressCountry": "RDC - République Démocratique du Congo",
            },
            "on_site",
        )
        assert location == f"Kinshasa, {HOME_COUNTRY}"

    def test_a_remote_ad_does_not_keep_the_city_filter_list(self):
        location = build_location(
            {
                "addressLocality": "/ Travail En Remote",
                "addressRegion": "Boende - Bukavu - Bunia - Buta - Gbadolite - International",
                "addressCountry": "RDC - République Démocratique du Congo",
            },
            "remote_global",
        )
        assert location == f"Remote, {HOME_COUNTRY}"

    @pytest.mark.parametrize(
        ("title", "locality", "region", "expected"),
        [
            ("Engineer", "Kinshasa", "Kinshasa", "on_site"),
            ("Engineer", "/ Travail En Remote", "Kinshasa", "remote_country"),
            ("Engineer", "/ Travail En Remote", "Boende - International", "remote_global"),
            (None, None, None, "on_site"),
        ],
    )
    def test_remote_detection(self, title, locality, region, expected):
        assert detect_remote(title, locality, region) == expected


class TestDatesAndIdentifier:
    def test_iso_date(self):
        assert parse_date("2026-11-19T01:00:02+00:00") == datetime(2026, 11, 19)

    @pytest.mark.parametrize("value", ["19.11.2026", "19/11/2026"])
    def test_day_first_french_date(self, value):
        assert parse_date(value) == datetime(2026, 11, 19)

    @pytest.mark.parametrize("value", [None, "", "TBD", "31/02/2026"])
    def test_unreadable_dates_are_none(self, value):
        assert parse_date(value) is None

    def test_identifier_value_wins_over_the_discovery_id(self):
        assert extract_identifier({"identifier": {"value": "515161"}}, "slug") == "515161"
        assert extract_identifier({"identifier": "296562"}, "slug") == "296562"
        assert extract_identifier({}, "slug") == "slug"


class TestJsonLd:
    def test_a_valid_block_is_read(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"].startswith("Business Development Lead")
        assert data["identifier"]["value"] == "515161"

    def test_unescaped_quotes_in_the_description_are_repaired(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(BROKEN_DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"] == "Responsable Transit (H/F) - Kinshasa"
        assert data["identifier"]["value"] == "506522"
        assert data["employmentType"] == "CDI"


class TestParser:
    def test_the_contract_is_fully_populated(self):
        job = EmploiCdParser().parse_job(_raw())
        assert job.source_job_id == "515161"
        assert job.job_title.startswith("Business Development Lead")
        assert job.company_name == "AFRICAWORK"
        assert job.location_cleaned == f"Kinshasa, {HOME_COUNTRY}"
        assert job.posting_date == datetime(2026, 11, 19)
        assert job.closing_date == datetime(2027, 1, 6)
        assert job.employment_type_code is None, "four advertised types are not one code"
        assert job.remote_work_type_code == "on_site"
        assert job.currency_iso_code == "CDF"
        assert job.pay_period == "monthly"
        assert job.description_clean and "logistics" in job.description_clean
        assert job.word_count > 20

    def test_no_salary_is_invented(self):
        job = EmploiCdParser().parse_job(_raw())
        assert job.salary_min is None and job.salary_max is None
        assert job.salary_disclosed is False

    def test_a_slug_only_url_still_gets_the_canonical_numeric_id(self):
        job = EmploiCdParser().parse_job(
            _raw(job_id="business-development-lead-beni-butembo-goma-bunia")
        )
        assert job.source_job_id == "515161"
        assert job.raw_payload["discovered_job_id"] == (
            "business-development-lead-beni-butembo-goma-bunia"
        )

    def test_the_broken_jsonld_ad_still_parses(self):
        job = EmploiCdParser().parse_job(
            _raw(BROKEN_DETAIL, "responsable-transit-hf-kinshasa-506522")
        )
        assert job.source_job_id == "506522"
        assert job.job_title == "Responsable Transit (H/F) - Kinshasa"
        assert job.company_name == "CFAO RDC"
        assert job.employment_type_code == "full_time"
        assert job.description_clean and "Responsable Transit" in job.description_clean

    def test_html_fallback_when_jsonld_is_absent(self):
        job = EmploiCdParser().parse_job(_raw(NO_JSONLD, "chauffeur-livreur"))
        assert job.source_job_id == "chauffeur-livreur"
        assert job.job_title == "Chauffeur Livreur"
        assert job.company_name == "TRANSPORT KIN SARL"
        assert job.location_cleaned == HOME_COUNTRY
        assert job.description_clean and "chauffeur" in job.description_clean
        assert job.employment_type_code is None

    def test_a_remote_ad_is_marked_remote_and_not_given_a_city_list(self):
        job = EmploiCdParser().parse_job(_raw(REMOTE_DETAIL, "consultant-sap-senior-hf-296562"))
        assert job.source_job_id == "296562"
        assert job.remote_work_type_code == "remote_global"
        assert job.location_cleaned == f"Remote, {HOME_COUNTRY}"
        assert job.employment_type_code is None, '"CDI - Freelance" is ambiguous'

    def test_html_entities_in_titles_are_decoded(self):
        html = DETAIL.replace(
            "Business Development Lead - Beni/Butembo/Goma/Bunia",
            "Apporteur d&#039;Affaires Indépendants",
        )
        job = EmploiCdParser().parse_job(_raw(html, "apporteur"))
        assert job.job_title == "Apporteur d'Affaires Indépendants"

    def test_a_closing_date_before_the_posting_is_dropped(self):
        html = DETAIL.replace("2027-01-06T00:00:00+00:00", "2026-11-01T00:00:00+00:00")
        job = EmploiCdParser().parse_job(_raw(html))
        assert job.closing_date is None

    def test_no_description_is_none_not_the_title(self):
        html = NO_JSONLD.replace(
            '<div class="job-description">Nous recherchons un chauffeur livreur '
            "pour Kinshasa.</div>",
            "",
        )
        job = EmploiCdParser().parse_job(_raw(html, "chauffeur-livreur"))
        assert job.description_clean is None
        assert job.word_count == 0

    def test_a_page_without_a_title_is_skipped_not_invented(self):
        raw = _raw("<html><body><p>nothing</p></body></html>", "bad")
        assert EmploiCdParser().parse_jobs([raw]) == []

    def test_one_bad_page_does_not_drop_the_good_ones(self):
        good = _raw()
        bad = _raw("<html><body><p>nothing</p></body></html>", "bad")
        jobs = EmploiCdParser().parse_jobs([good, bad])
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "515161"

    def test_skills_are_extracted_from_the_description(self):
        job = EmploiCdParser().parse_job(_raw())
        assert "Python" in job.skills
        assert "Excel" in job.skills


class TestPipelineDryRun:
    class _Client:
        def __init__(self, targets, raws, pages=4):
            self.targets = targets
            self.raws = raws
            self.pages = pages

        def fetch_job_urls(self, max_jobs=None):
            return self.targets, self.pages

        def fetch_all_details(self, targets):
            return self.raws

    def test_a_dry_run_parses_without_persisting(self):
        client = self._Client(
            [("https://www.emploi.cd/ad", "x")],
            [_raw()],
            pages=4,
        )
        result = EmploiCdPipeline(settings=EmploiCdSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.pages_scraped == 4
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 0
        assert result.failed_count == 0

    def test_zero_discovered_postings_is_reported(self):
        client = self._Client([], [], pages=1)
        result = EmploiCdPipeline(settings=EmploiCdSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.validation_passed is False
        assert result.parsed_count == 0
        assert any("Zero job items" in issue for issue in result.issues)

    def test_zero_parsed_postings_fails_validation(self):
        client = self._Client(
            [("https://www.emploi.cd/ad", "x")],
            [_raw("<html></html>", "bad")],
        )
        result = EmploiCdPipeline(settings=EmploiCdSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.validation_passed is False
        assert any("Zero jobs successfully parsed" in issue for issue in result.issues)

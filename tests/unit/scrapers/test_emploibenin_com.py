"""Unit tests for the Emploi Bénin (Benin) scraper.

Pinned measured facts (2026-11-20, live site):

  * The search directory is ``/recherche-jobs-benin``; page 1 has no query
    string and page N uses ``?page=N``.
  * The board held 209 offers over 9 pages (25 x 8 plus a final page of 9),
    with no URL overlap between pages.
  * Ad URLs live under ``/offre-emploi-benin/<slug>``; most slugs end in the
    numeric ad id but not all do.
  * Every sampled detail page carries a Schema.org ``JobPosting`` block whose
    ``identifier.value`` is the canonical ad id.
  * ``employmentType`` is often the multi-value
    ``"Freelance - Temps partiel"`` or ``"CDI - Freelance"``.
  * ``jobLocation.address.addressCountry`` is the plain label ``Benin``.
  * ``jobLocation.address.addressRegion`` is NOT a region: it is the list of
    cities the ad is open to (``"Abomey - Abomey-Calavi - Cotonou"``), so it
    must never be stored as a place.
  * One sampled ad's JSON-LD contains unescaped double quotes inside
    ``description`` -- the same defect Emploi.ci and Emploi.cd have.
  * ``baseSalary`` was absent on every sampled ad.

No test touches the network.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.scrapers.emploibenin_com import (
    EmploiBeninClient,
    EmploiBeninParser,
    EmploiBeninPipeline,
    EmploiBeninResponseError,
    EmploiBeninSettings,
    RawEmploiBeninJob,
    job_id_from_href,
)
from job_market_intel.scrapers.emploibenin_com.parser import (
    HOME_COUNTRY,
    build_location,
    detect_remote,
    extract_identifier,
    extract_json_ld,
    map_employment_type,
    normalize_country,
    parse_date,
)

_BJ_AD_PREFIX = "/offre-emploi-benin/"

LISTING_PAGE_0 = f"""<html><body>
<a href="{_BJ_AD_PREFIX}agent-livraison-cotonou-510021">Livraison</a>
<a href="{_BJ_AD_PREFIX}executive-assistant-senior-fr-ou-fren-cotonou-507960">Assistant</a>
<a href="/recherche-jobs-benin?page=1">2</a>
<a href="https://www.emploi.ci">Côte d'Ivoire</a>
</body></html>"""

LISTING_PAGE_1 = f"""<html><body>
<a href="{_BJ_AD_PREFIX}executive-assistant-senior-fr-ou-fren-cotonou-507960">Assistant</a>
<a href="{_BJ_AD_PREFIX}consultant-sap-senior-hf-258278">SAP</a>
</body></html>"""

#: The live ads put every city they are open to into ``addressRegion``. Kept as
#: a real long value (assembled here so no source line is unreadably wide).
_REGION = " - ".join(
    [
        "Abomey",
        "Abomey-Calavi",
        "Cotonou",
        "Parakou",
        "Porto-Novo",
        "Natitingou",
        "Bohicon",
        "Ouidah",
        "Lokossa",
        "Djougou",
    ]
)

DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-19T01:00:02+00:00",
  "title": "Executive Assistant Senior FR Ou FR/EN - Cotonou",
  "identifier": {"@type": "PropertyValue", "name": "AFRICAWORK", "value": "507960"},
  "validThrough": "2027-01-06T00:00:00+00:00",
  "employmentType": "CDI",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICAWORK"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Cotonou",
    "addressRegion": "__REGION__",
    "addressCountry": "Benin"
  }},
  "baseSalary": null,
  "description": "<p>We are searching for an Executive Assistant Senior.</p>"
}
</script>
<script type="application/ld+json">
{"@context": "http://schema.org", "@type": "WebSite", "name": "Emploi Bénin",}
</script>
</head><body>
<h1>Executive Assistant Senior FR Ou FR/EN - Cotonou</h1>
<h3>AFRICAWORK</h3>
<div class="job-description">
  We are searching for an Executive Assistant Senior for our client, a logistics
  solutions company operating across Benin. The role covers calendar management,
  reporting, travel coordination and the supervision of a small administrative
  team. Python and Excel are useful for the monthly dashboards. Fluent French and
  English are required. Send your CV and a short cover letter describing your
  experience supporting senior management in a fast moving environment.
</div>
</body></html>""".replace("__REGION__", _REGION)

#: The live defect: unescaped double quotes inside the JSON-LD description.
BROKEN_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-18T13:55:01+00:00",
  "title": "Chef Cuisine - Siège de Lagos (Expatrié Béninois)",
  "description": "<p align="left">Nous sommes à la recherche d'un Chef Cuisine.</p>
<p align="left"><strong>Missions</strong></p>",
  "identifier": {"@type": "PropertyValue", "name": "GROUPE ADEV", "value": "504285"},
  "validThrough": "2026-12-11T16:15:41+00:00",
  "employmentType": "CDI",
  "hiringOrganization": {"@type": "Organization", "name": "GROUPE ADEV"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Siège De Lagos (Expatrié Béninois)",
    "addressRegion": "International",
    "addressCountry": "Benin"
  }}
}
</script>
</head><body>
<h1>Chef Cuisine - Siège de Lagos (Expatrié Béninois)</h1>
<h3>GROUPE ADEV</h3>
<div class="job-description">Nous sommes à la recherche d'un Chef Cuisine.
Missions : superviser la brigade et garantir la qualité des plats servis.</div>
</body></html>"""

#: No JSON-LD at all: the HTML fallback must still produce a row.
NO_JSONLD = """<!DOCTYPE html><html><body>
<h1>Chauffeur Livreur</h1>
<h3>TRANSPORT COTONOU SARL</h3>
<div class="job-description">Nous recherchons un chauffeur livreur pour Cotonou.</div>
</body></html>"""

AGENT_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-17T08:12:00+00:00",
  "title": "Agent de Livraison - Cotonou",
  "identifier": {"@type": "PropertyValue", "name": "AFRICAWORK", "value": "510021"},
  "validThrough": "2027-02-01T00:00:00+00:00",
  "employmentType": "Freelance - Temps partiel",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICAWORK"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Cotonou",
    "addressRegion": "Abomey-Calavi - Cotonou",
    "addressCountry": "Benin"
  }}
}
</script>
</head><body>
<h1>Agent de Livraison - Cotonou</h1>
<h3>AFRICAWORK</h3>
<div class="job-description">Livraison de colis dans Cotonou. Permis A requis.</div>
</body></html>"""

REMOTE_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-09-29T09:32:40+00:00",
  "title": "Consultant SAP Senior (H/F)",
  "identifier": {"@type": "PropertyValue", "name": "AFRICASHORE", "value": "258278"},
  "validThrough": "2027-03-31T23:59:00+00:00",
  "employmentType": "CDI - Freelance",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICASHORE"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "/ Travail à Distance",
    "addressRegion": "Cotonou - Parakou - International",
    "addressCountry": "Benin"
  }}
}
</script>
</head><body>
<h1>Consultant SAP Senior (H/F)</h1>
<h3>AFRICASHORE</h3>
<div class="job-description">Nous recherchons un Consultant SAP Sénior (H/F).</div>
</body></html>"""


def _raw(html: str = DETAIL, job_id: str = "executive-assistant-senior-fr-ou-fren-cotonou-507960"):
    return RawEmploiBeninJob(
        url=f"https://www.emploibenin.com/offre-emploi-benin/{job_id}",
        job_id=job_id,
        html_content=html,
    )


class TestJobIdFromHref:
    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            ("/offre-emploi-benin/agent-livraison-cotonou-510021", "510021"),
            (
                "https://www.emploibenin.com/offre-emploi-benin/"
                "executive-assistant-senior-fr-ou-fren-cotonou-507960",
                "507960",
            ),
            (
                "/offre-emploi-benin/consultant-sap-senior-hf-258278/",
                "258278",
            ),
            (
                "/offre-emploi-benin/consultant-sap-senior-hf-258278?x=1",
                "258278",
            ),
            ("/offre-emploi-benin/no-numeric-id", "no-numeric-id"),
            ("/recherche-jobs-benin?page=1", None),
            ("https://www.emploi.ci", None),
            ("", None),
        ],
    )
    def test_discovery_id(self, href, expected):
        assert job_id_from_href(href) == expected


class TestListingUrl:
    def test_page_one_has_no_query_string(self):
        client = EmploiBeninClient(EmploiBeninSettings(rate_limit_delay=0))
        assert client.listing_url(0) == "https://www.emploibenin.com/recherche-jobs-benin"
        assert client.listing_url(1) == ("https://www.emploibenin.com/recherche-jobs-benin?page=1")
        assert client.listing_url(3) == ("https://www.emploibenin.com/recherche-jobs-benin?page=3")


class TestDiscovery:
    def test_ads_are_deduped_and_sibling_country_links_ignored(self):
        client = EmploiBeninClient(EmploiBeninSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else LISTING_PAGE_1
        found, pages_scraped = client.discover_job_urls(max_pages=3)
        assert pages_scraped == 3
        ids = {discovery_id for _, discovery_id in found}
        assert ids == {
            "510021",
            "507960",
            "258278",
        }

    def test_a_page_with_no_new_links_stops_discovery(self):
        client = EmploiBeninClient(EmploiBeninSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else "<html></html>"
        found, pages_scraped = client.discover_job_urls(max_pages=5)
        assert len(found) == 2
        assert pages_scraped == 2

    def test_an_empty_board_raises_rather_than_returning_nothing(self):
        client = EmploiBeninClient(EmploiBeninSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: "<html><body></body></html>"
        with pytest.raises(EmploiBeninResponseError, match="markup changed"):
            client.discover_job_urls(max_pages=2)

    def test_fetch_job_urls_applies_the_budget(self):
        client = EmploiBeninClient(
            EmploiBeninSettings(rate_limit_delay=0, max_jobs_per_run=2, fresh_rows=2)
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
        client = EmploiBeninClient(EmploiBeninSettings(rate_limit_delay=0))
        assert client.select_window(self._items(5), 10) == self._items(5)

    def test_the_newest_rows_are_always_taken(self):
        client = EmploiBeninClient(
            EmploiBeninSettings(rate_limit_delay=0, fresh_rows=3, start_offset=0)
        )
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0002", "0003", "0004"]

    def test_the_tail_window_rotates(self):
        client = EmploiBeninClient(
            EmploiBeninSettings(rate_limit_delay=0, fresh_rows=2, start_offset=4)
        )
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0006", "0007", "0008"]

    def test_the_window_wraps_around_the_tail(self):
        client = EmploiBeninClient(
            EmploiBeninSettings(rate_limit_delay=0, fresh_rows=0, start_offset=8)
        )
        chosen = client.select_window(self._items(10), 4)
        assert [jid for _, jid in chosen] == ["0008", "0009", "0000", "0001"]

    def test_the_offset_advances_one_window_per_day(self):
        client = EmploiBeninClient(EmploiBeninSettings(rate_limit_delay=0, fresh_rows=0))
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
            ("Freelance - Temps partiel", None),
            ("CDI - CDD - Freelance", None),
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
        assert normalize_country("Benin") == HOME_COUNTRY
        assert normalize_country("Bénin") == HOME_COUNTRY
        assert normalize_country("BJ") == HOME_COUNTRY
        assert normalize_country("BEN") == HOME_COUNTRY
        assert normalize_country("France") == "France"

    def test_a_normal_address_keeps_the_city_and_country(self):
        location = build_location(
            {
                "addressLocality": "Cotonou",
                "addressRegion": "Abomey - Abomey-Calavi - Cotonou - Parakou",
                "addressCountry": "Benin",
            },
            "on_site",
        )
        assert location == f"Cotonou, {HOME_COUNTRY}"
        assert "Abomey" not in location, "the city list is not a region"

    def test_a_city_list_region_is_never_appended(self):
        location = build_location(
            {
                "addressLocality": "Parakou",
                "addressRegion": "Abomey-Calavi - Cotonou",
                "addressCountry": "Benin",
            },
            "on_site",
        )
        assert location == f"Parakou, {HOME_COUNTRY}"

    def test_an_identical_city_and_region_is_not_repeated(self):
        location = build_location(
            {
                "addressLocality": "Cotonou",
                "addressRegion": "Cotonou",
                "addressCountry": "Benin",
            },
            "on_site",
        )
        assert location == f"Cotonou, {HOME_COUNTRY}"

    def test_a_remote_ad_does_not_keep_the_city_filter_list(self):
        location = build_location(
            {
                "addressLocality": "/ Travail à Distance",
                "addressRegion": "Cotonou - Parakou - International",
                "addressCountry": "Benin",
            },
            "remote_global",
        )
        assert location == f"Remote, {HOME_COUNTRY}"

    def test_an_online_ad_is_marked_remote_and_named_remote(self):
        location = build_location(
            {
                "addressLocality": "En Ligne",
                "addressRegion": "International",
                "addressCountry": "Benin",
            },
            "remote_global",
        )
        assert location == f"Remote, {HOME_COUNTRY}"

    def test_a_missing_country_falls_back_to_benin(self):
        location = build_location({"addressLocality": "Cotonou"}, "on_site")
        assert location == f"Cotonou, {HOME_COUNTRY}"

    @pytest.mark.parametrize(
        ("title", "locality", "region", "expected"),
        [
            ("Engineer", "Cotonou", "Cotonou", "on_site"),
            ("Engineer", "/ Travail En Remote", "Cotonou", "remote_country"),
            ("Engineer", "/ Travail à Distance", "Cotonou - International", "remote_global"),
            ("Monteur Vidéo", "En Ligne", "International", "remote_global"),
            ("Monteur Vidéo", "En Ligne", "Cotonou", "remote_country"),
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
        assert extract_identifier({"identifier": {"value": "507960"}}, "slug") == "507960"
        assert extract_identifier({"identifier": "258278"}, "slug") == "258278"
        assert extract_identifier({}, "slug") == "slug"


class TestJsonLd:
    def test_a_valid_block_is_read(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"].startswith("Executive Assistant")
        assert data["identifier"]["value"] == "507960"

    def test_unescaped_quotes_in_the_description_are_repaired(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(BROKEN_DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"] == "Chef Cuisine - Siège de Lagos (Expatrié Béninois)"
        assert data["identifier"]["value"] == "504285"
        assert data["employmentType"] == "CDI"


class TestParser:
    def test_the_contract_is_fully_populated(self):
        job = EmploiBeninParser().parse_job(_raw())
        assert job.source_job_id == "507960"
        assert job.job_title.startswith("Executive Assistant")
        assert job.company_name == "AFRICAWORK"
        assert job.location_cleaned == f"Cotonou, {HOME_COUNTRY}"
        assert job.posting_date == datetime(2026, 11, 19)
        assert job.closing_date == datetime(2027, 1, 6)
        assert job.employment_type_code == "full_time"
        assert job.remote_work_type_code == "on_site"
        assert job.currency_iso_code == "XOF"
        assert job.pay_period == "monthly"
        assert job.description_clean and "logistics" in job.description_clean
        assert job.word_count > 20

    def test_no_salary_is_invented(self):
        job = EmploiBeninParser().parse_job(_raw())
        assert job.salary_min is None and job.salary_max is None
        assert job.salary_disclosed is False

    def test_the_city_list_is_not_in_the_clean_location(self):
        job = EmploiBeninParser().parse_job(_raw())
        assert "Abomey" not in job.location_cleaned
        assert "Parakou" not in job.location_cleaned

    def test_a_slug_only_url_still_gets_the_canonical_numeric_id(self):
        job = EmploiBeninParser().parse_job(
            _raw(job_id="executive-assistant-senior-fr-ou-fren-cotonou-507960")
        )
        assert job.source_job_id == "507960"
        assert job.raw_payload["discovered_job_id"] == (
            "executive-assistant-senior-fr-ou-fren-cotonou-507960"
        )

    def test_the_broken_jsonld_ad_still_parses(self):
        job = EmploiBeninParser().parse_job(
            _raw(BROKEN_DETAIL, "chef-cuisine-siege-lagos-expatrie-beninois-504285")
        )
        assert job.source_job_id == "504285"
        assert job.job_title == "Chef Cuisine - Siège de Lagos (Expatrié Béninois)"
        assert job.company_name == "GROUPE ADEV"
        assert job.employment_type_code == "full_time"
        assert job.description_clean and "Chef Cuisine" in job.description_clean

    def test_html_fallback_when_jsonld_is_absent(self):
        job = EmploiBeninParser().parse_job(_raw(NO_JSONLD, "chauffeur-livreur"))
        assert job.source_job_id == "chauffeur-livreur"
        assert job.job_title == "Chauffeur Livreur"
        assert job.company_name == "TRANSPORT COTONOU SARL"
        assert job.location_cleaned == HOME_COUNTRY
        assert job.description_clean and "chauffeur" in job.description_clean
        assert job.employment_type_code is None

    def test_a_remote_ad_is_marked_remote_and_not_given_a_city_list(self):
        job = EmploiBeninParser().parse_job(_raw(REMOTE_DETAIL, "consultant-sap-senior-hf-258278"))
        assert job.source_job_id == "258278"
        assert job.remote_work_type_code == "remote_global"
        assert job.location_cleaned == f"Remote, {HOME_COUNTRY}"
        assert job.employment_type_code is None, '"CDI - Freelance" is ambiguous'

    def test_a_multi_value_employment_type_is_ambiguous(self):
        job = EmploiBeninParser().parse_job(_raw(AGENT_DETAIL, "agent-livraison-cotonou-510021"))
        assert job.source_job_id == "510021"
        assert job.job_title == "Agent de Livraison - Cotonou"
        assert job.employment_type_code is None, '"Freelance - Temps partiel" is two values'
        assert job.raw_payload["employment_type_raw"] == "Freelance - Temps partiel"

    def test_html_entities_in_titles_are_decoded(self):
        html = DETAIL.replace(
            "Executive Assistant Senior FR Ou FR/EN - Cotonou",
            "Assistant d&#039;Direction",
        )
        job = EmploiBeninParser().parse_job(_raw(html, "assistant"))
        assert job.job_title == "Assistant d'Direction"

    def test_a_closing_date_before_the_posting_is_dropped(self):
        html = DETAIL.replace("2027-01-06T00:00:00+00:00", "2026-11-01T00:00:00+00:00")
        job = EmploiBeninParser().parse_job(_raw(html))
        assert job.closing_date is None

    def test_no_description_is_none_not_the_title(self):
        html = NO_JSONLD.replace(
            '<div class="job-description">Nous recherchons un chauffeur livreur '
            "pour Cotonou.</div>",
            "",
        )
        job = EmploiBeninParser().parse_job(_raw(html, "chauffeur-livreur"))
        assert job.description_clean is None
        assert job.word_count == 0

    def test_a_page_without_a_title_is_skipped_not_invented(self):
        raw = _raw("<html><body><p>nothing</p></body></html>", "bad")
        assert EmploiBeninParser().parse_jobs([raw]) == []

    def test_one_bad_page_does_not_drop_the_good_ones(self):
        good = _raw()
        bad = _raw("<html><body><p>nothing</p></body></html>", "bad")
        jobs = EmploiBeninParser().parse_jobs([good, bad])
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "507960"

    def test_skills_are_extracted_from_the_description(self):
        job = EmploiBeninParser().parse_job(_raw())
        assert "Python" in job.skills
        assert "Excel" in job.skills


class TestPipelineDryRun:
    class _Client:
        def __init__(self, targets, raws, pages=9):
            self.targets = targets
            self.raws = raws
            self.pages = pages

        def fetch_job_urls(self, max_jobs=None):
            return self.targets, self.pages

        def fetch_all_details(self, targets):
            return self.raws

    def test_a_dry_run_parses_without_persisting(self):
        client = self._Client(
            [("https://www.emploibenin.com/offre-emploi-benin/ad-507960", "x")],
            [_raw()],
            pages=9,
        )
        result = EmploiBeninPipeline(
            settings=EmploiBeninSettings(rate_limit_delay=0), client=client
        ).run(store_db=False)
        assert result.pages_scraped == 9
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 0
        assert result.failed_count == 0

    def test_zero_discovered_postings_is_reported(self):
        client = self._Client([], [], pages=1)
        result = EmploiBeninPipeline(
            settings=EmploiBeninSettings(rate_limit_delay=0), client=client
        ).run(store_db=False)
        assert result.validation_passed is False
        assert result.parsed_count == 0
        assert any("Zero job items" in issue for issue in result.issues)

    def test_zero_parsed_postings_fails_validation(self):
        client = self._Client(
            [("https://www.emploibenin.com/offre-emploi-benin/ad", "x")],
            [_raw("<html></html>", "bad")],
        )
        result = EmploiBeninPipeline(
            settings=EmploiBeninSettings(rate_limit_delay=0), client=client
        ).run(store_db=False)
        assert result.validation_passed is False
        assert any("Zero jobs successfully parsed" in issue for issue in result.issues)

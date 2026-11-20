"""Unit tests for the Emploi.cm (Cameroon) scraper.

Pinned measured facts (2026-11-20, live site):

  * The search directory is ``/recherche-jobs-cameroun``; page 1 has no query
    string and page N uses ``?page=N``.
  * The board held 418 unique offers over 17 pages (sixteen pages of 25 ad
    links plus a final page of 19; 419 links, one URL repeating across pages).
    A page past the last one returns HTTP 200 with zero ad links.
  * Ad URLs live under ``/offre-emploi-cameroun/<slug>`` and every sampled slug
    ends in the numeric ad id.
  * Every sampled detail page carries a Schema.org ``JobPosting`` block whose
    ``identifier.value`` is the canonical ad id.
  * ``jobLocation.address.addressCountry`` is the French label ``Cameroun``.
  * ``jobLocation.address.addressRegion`` is NOT a region: it is the list of
    cities the ad is open to (``"Douala - Yaoundé"``), so it must never be
    stored as a place.
  * One sampled ad -- the Djibouti expatriation role -- has the same
    unescaped-quote JSON-LD defect as Emploi.ci, Emploi.cd and Emploi Bénin.
  * ``baseSalary`` was absent on every sampled ad.

No test touches the network.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.scrapers.emploi_cm import (
    EmploiCmClient,
    EmploiCmParser,
    EmploiCmPipeline,
    EmploiCmResponseError,
    EmploiCmSettings,
    RawEmploiCmJob,
    job_id_from_href,
)
from job_market_intel.scrapers.emploi_cm.parser import (
    HOME_COUNTRY,
    build_location,
    detect_remote,
    extract_identifier,
    extract_json_ld,
    map_employment_type,
    normalize_country,
    parse_date,
)

_AD_PREFIX = "/offre-emploi-cameroun/"

LISTING_PAGE_0 = f"""<html><body>
<a href="{_AD_PREFIX}commercial-douala-1253954">Commercial</a>
<a href="{_AD_PREFIX}chatgee-trafic-social-seo-yaounde-1256195">SEA</a>
<a href="/recherche-jobs-cameroun?page=1">2</a>
<a href="https://www.emploi.ci">Côte d'Ivoire</a>
</body></html>"""

LISTING_PAGE_1 = f"""<html><body>
<a href="{_AD_PREFIX}chatgee-trafic-social-seo-yaounde-1256195">SEA</a>
<a href="{_AD_PREFIX}agent-livraison-douala-510021">Livraison</a>
</body></html>"""

#: The live ads put every city they are open to into ``addressRegion``. Kept as
#: a real long value (assembled here so no source line is unreadably wide).
_REGION = " - ".join(
    [
        "Douala",
        "Yaoundé",
        "Bafoussam",
        "Garoua",
        "Bamenda",
        "Maroua",
        "Buea",
        "Kribi",
        "Limbe",
        "Ngaoundéré",
    ]
)

DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-20T01:00:01+01:00",
  "title": "Commercial - Douala",
  "identifier": {"@type": "PropertyValue", "name": "LOSAC SARL", "value": "1253954"},
  "validThrough": "2026-12-26T10:45:03+01:00",
  "employmentType": "CDI",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "LOSAC SARL",
    "sameAs": "https://www.emploi.cm/offre-emploi-cameroun/commercial-douala-1253954"
  },
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Douala",
    "addressRegion": "__REGION__",
    "addressCountry": "Cameroun"
  }},
  "baseSalary": null,
  "description": "<p>Une entreprise recrute des commerciaux à Douala.</p>"
}
</script>
<script type="application/ld+json">
{"@context": "http://schema.org", "@type": "WebSite", "name": "Emploi.cm",}
</script>
</head><body>
<h1>Commercial - Douala</h1>
<h3>LOSAC SARL</h3>
<div class="job-description">
  Dans le cadre du développement de ses activités, une entreprise recrute des
  commerciaux dynamiques pour renforcer son équipe à Douala. Le poste couvre la
  prospection de nouveaux clients, la négociation, le suivi des commandes et le
  reporting hebdomadaire. Une bonne maîtrise d'Excel et du CRM est attendue,
  ainsi qu'une expérience confirmée de la vente en milieu industriel. Le
  candidat idéal parle français et anglais et gère son planning de manière
  autonome. Rémunération motivante selon profil.
</div>
</body></html>""".replace("__REGION__", _REGION)

#: The live defect, measured on the Djibouti expatriation ad: unescaped double
#: quotes inside the JSON-LD description. Note the block keeps a readable
#: jobLocation/country and only the description field is broken.
BROKEN_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-20T01:00:01+01:00",
  "title": "Infirmier Formateur Clinique H/F - (Expatriation : Djibouti) - Djibouti",
  "description": "<p align="left">Un hôpital privé à Djibouti recrute un(e) infirmier.</p>
<p align="left"><strong>Missions</strong></p>",
  "identifier": {"@type": "PropertyValue", "name": "AFRICAWORK", "value": "1255712"},
  "validThrough": "2026-12-23T00:00:00+01:00",
  "employmentType": "CDI",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICAWORK"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Djibouti",
    "addressRegion": "International",
    "addressCountry": "Cameroun"
  }}
}
</script>
</head><body>
<h1>Infirmier Formateur Clinique H/F - (Expatriation : Djibouti) - Djibouti</h1>
<h3>AFRICAWORK</h3>
<div class="job-description">Un hôpital privé de premier plan à Djibouti recherche
un(e) infirmier formateur clinique. Missions : encadrer les équipes soignantes,
organiser les formations et garantir la qualité des soins.</div>
</body></html>"""

#: No JSON-LD at all: the HTML fallback must still produce a row.
NO_JSONLD = """<!DOCTYPE html><html><body>
<h1>Chauffeur Livreur</h1>
<h3>TRANSPORT DOUALA SARL</h3>
<div class="job-description">Nous recherchons un chauffeur livreur pour Douala.</div>
</body></html>"""

AGENT_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-11-17T08:12:00+01:00",
  "title": "Agent de Livraison - Douala",
  "identifier": {"@type": "PropertyValue", "name": "AFRICAWORK", "value": "510021"},
  "validThrough": "2027-02-01T00:00:00+01:00",
  "employmentType": "CDI - CDD - Intérim - Freelance",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICAWORK"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "Douala",
    "addressRegion": "Yaoundé - Douala",
    "addressCountry": "Cameroun"
  }}
}
</script>
</head><body>
<h1>Agent de Livraison - Douala</h1>
<h3>AFRICAWORK</h3>
<div class="job-description">Livraison de colis dans Douala. Permis A requis.</div>
</body></html>"""

#: The work-from-anywhere address shape the AfricaWork sister boards use: a
#: slash-prefixed locality plus "International" in the city list. The detection
#: contract is what is under test, not the existence of this exact ad.
REMOTE_DETAIL = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "datePosted": "2026-09-29T09:32:40+01:00",
  "title": "Consultant SAP Senior (H/F)",
  "identifier": {"@type": "PropertyValue", "name": "AFRICASHORE", "value": "258278"},
  "validThrough": "2027-03-31T23:59:00+01:00",
  "employmentType": "CDI - Freelance",
  "hiringOrganization": {"@type": "Organization", "name": "AFRICASHORE"},
  "jobLocation": {"@type": "Place", "address": {
    "@type": "PostalAddress",
    "addressLocality": "/ Travail à Distance",
    "addressRegion": "Douala - Garoua - International",
    "addressCountry": "Cameroun"
  }}
}
</script>
</head><body>
<h1>Consultant SAP Senior (H/F)</h1>
<h3>AFRICASHORE</h3>
<div class="job-description">Nous recherchons un Consultant SAP Sénior (H/F).</div>
</body></html>"""


def _raw(html: str = DETAIL, job_id: str = "commercial-douala-1253954"):
    return RawEmploiCmJob(
        url=f"https://www.emploi.cm/offre-emploi-cameroun/{job_id}",
        job_id=job_id,
        html_content=html,
    )


class TestJobIdFromHref:
    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            ("/offre-emploi-cameroun/commercial-douala-1253954", "1253954"),
            (
                "https://www.emploi.cm/offre-emploi-cameroun/"
                "chatgee-trafic-social-seo-yaounde-1256195",
                "1256195",
            ),
            (
                "/offre-emploi-cameroun/"
                "infirmier-formateur-clinique-hf-expatriation-djibouti-djibouti-1255712/",
                "1255712",
            ),
            (
                "/offre-emploi-cameroun/commercial-douala-1253954?x=1",
                "1253954",
            ),
            ("/offre-emploi-cameroun/no-numeric-id", "no-numeric-id"),
            ("/recherche-jobs-cameroun?page=1", None),
            ("https://www.emploi.ci", None),
            ("", None),
        ],
    )
    def test_discovery_id(self, href, expected):
        assert job_id_from_href(href) == expected


class TestListingUrl:
    def test_page_one_has_no_query_string(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0))
        assert client.listing_url(0) == "https://www.emploi.cm/recherche-jobs-cameroun"
        assert client.listing_url(1) == ("https://www.emploi.cm/recherche-jobs-cameroun?page=1")
        assert client.listing_url(3) == ("https://www.emploi.cm/recherche-jobs-cameroun?page=3")


class TestDiscovery:
    def test_ads_are_deduped_and_sibling_country_links_ignored(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else LISTING_PAGE_1
        found, pages_scraped = client.discover_job_urls(max_pages=3)
        assert pages_scraped == 3
        ids = {discovery_id for _, discovery_id in found}
        assert ids == {
            "1253954",
            "1256195",
            "510021",
        }

    def test_a_page_with_no_new_links_stops_discovery(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: LISTING_PAGE_0 if "page=" not in url else "<html></html>"
        found, pages_scraped = client.discover_job_urls(max_pages=5)
        assert len(found) == 2
        assert pages_scraped == 2

    def test_an_empty_board_raises_rather_than_returning_nothing(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: "<html><body></body></html>"
        with pytest.raises(EmploiCmResponseError, match="markup changed"):
            client.discover_job_urls(max_pages=2)

    def test_fetch_job_urls_applies_the_budget(self):
        client = EmploiCmClient(
            EmploiCmSettings(rate_limit_delay=0, max_jobs_per_run=2, fresh_rows=2)
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
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0))
        assert client.select_window(self._items(5), 10) == self._items(5)

    def test_the_newest_rows_are_always_taken(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0, fresh_rows=3, start_offset=0))
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0002", "0003", "0004"]

    def test_the_tail_window_rotates(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0, fresh_rows=2, start_offset=4))
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0006", "0007", "0008"]

    def test_the_window_wraps_around_the_tail(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0, fresh_rows=0, start_offset=8))
        chosen = client.select_window(self._items(10), 4)
        assert [jid for _, jid in chosen] == ["0008", "0009", "0000", "0001"]

    def test_the_offset_advances_one_window_per_day(self):
        client = EmploiCmClient(EmploiCmSettings(rate_limit_delay=0, fresh_rows=0))
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
        assert normalize_country("Cameroon") == HOME_COUNTRY
        assert normalize_country("Cameroun") == HOME_COUNTRY
        assert normalize_country("CM") == HOME_COUNTRY
        assert normalize_country("CMR") == HOME_COUNTRY
        assert normalize_country("France") == "France"

    def test_a_normal_address_keeps_the_city_and_country(self):
        location = build_location(
            {
                "addressLocality": "Douala",
                "addressRegion": "Bafoussam - Yaoundé - Douala - Garoua",
                "addressCountry": "Cameroon",
            },
            "on_site",
        )
        assert location == f"Douala, {HOME_COUNTRY}"
        assert "Bafoussam" not in location, "the city list is not a region"

    def test_a_city_list_region_is_never_appended(self):
        location = build_location(
            {
                "addressLocality": "Garoua",
                "addressRegion": "Yaoundé - Douala",
                "addressCountry": "Cameroon",
            },
            "on_site",
        )
        assert location == f"Garoua, {HOME_COUNTRY}"

    def test_an_identical_city_and_region_is_not_repeated(self):
        location = build_location(
            {
                "addressLocality": "Douala",
                "addressRegion": "Douala",
                "addressCountry": "Cameroon",
            },
            "on_site",
        )
        assert location == f"Douala, {HOME_COUNTRY}"

    def test_a_remote_ad_does_not_keep_the_city_filter_list(self):
        location = build_location(
            {
                "addressLocality": "/ Travail à Distance",
                "addressRegion": "Douala - Garoua - International",
                "addressCountry": "Cameroon",
            },
            "remote_global",
        )
        assert location == f"Remote, {HOME_COUNTRY}"

    def test_an_online_ad_is_marked_remote_and_named_remote(self):
        location = build_location(
            {
                "addressLocality": "En Ligne",
                "addressRegion": "International",
                "addressCountry": "Cameroon",
            },
            "remote_global",
        )
        assert location == f"Remote, {HOME_COUNTRY}"

    def test_a_missing_country_falls_back_to_cameroon(self):
        location = build_location({"addressLocality": "Douala"}, "on_site")
        assert location == f"Douala, {HOME_COUNTRY}"

    def test_a_country_label_locality_is_not_repeated(self):
        # Measured: some ads write "Cameroun" into addressLocality, so the
        # naive join produced the nonsense "Cameroun, Cameroon".
        location = build_location(
            {
                "addressLocality": "Cameroun",
                "addressRegion": "Bafoussam - Bamenda - Bertoua - Douala - Garoua - Yaoundé",
                "addressCountry": "Cameroun",
            },
            "on_site",
        )
        assert location == HOME_COUNTRY

    def test_a_multi_city_locality_is_dropped(self):
        # Measured: the five-city ad puts the filter list in addressLocality
        # (space-separated, trailing blanks) and the same set in addressRegion.
        location = build_location(
            {
                "addressLocality": "Douala Yaoundé Bafoussam Garoua Maroua  ",
                "addressRegion": "Bafoussam - Douala - Maroua - Yaoundé",
                "addressCountry": "Cameroun",
            },
            "on_site",
        )
        assert location == HOME_COUNTRY

    @pytest.mark.parametrize(
        "locality",
        ["Yaoundé Damas", "Yaoundé Mbalngong", "Douala Bonabéri"],
    )
    def test_a_two_token_locality_is_a_place_not_a_list(self, locality):
        location = build_location(
            {
                "addressLocality": locality,
                "addressRegion": "Douala - Yaoundé",
                "addressCountry": "Cameroun",
            },
            "on_site",
        )
        assert location == f"{locality}, {HOME_COUNTRY}"

    def test_a_long_place_name_without_a_matching_region_is_kept(self):
        location = build_location(
            {
                "addressLocality": "Quartier Des Palmiers",
                "addressRegion": "",
                "addressCountry": "Cameroun",
            },
            "on_site",
        )
        assert location == f"Quartier Des Palmiers, {HOME_COUNTRY}"

    def test_the_city_list_rule_needs_two_region_matches(self):
        # Three tokens but only one appears in the region: not the board's
        # filter list, so the locality is a real (if unusual) place name.
        location = build_location(
            {
                "addressLocality": "Douala Port Ancien",
                "addressRegion": "Douala - International",
                "addressCountry": "Cameroun",
            },
            "on_site",
        )
        assert location == f"Douala Port Ancien, {HOME_COUNTRY}"

    @pytest.mark.parametrize(
        ("title", "locality", "region", "expected"),
        [
            ("Engineer", "Douala", "Douala", "on_site"),
            ("Engineer", "/ Travail En Remote", "Douala", "remote_country"),
            ("Engineer", "/ Travail à Distance", "Douala - International", "remote_global"),
            ("Monteur Vidéo", "En Ligne", "International", "remote_global"),
            ("Monteur Vidéo", "En Ligne", "Douala", "remote_country"),
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
        assert data["title"] == "Commercial - Douala"
        assert data["identifier"]["value"] == "1253954"

    def test_unescaped_quotes_in_the_description_are_repaired(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(BROKEN_DETAIL, "html.parser")
        data = extract_json_ld(soup)
        assert data["title"] == (
            "Infirmier Formateur Clinique H/F - (Expatriation : Djibouti) - Djibouti"
        )
        assert data["identifier"]["value"] == "1255712"
        assert data["employmentType"] == "CDI"


class TestParser:
    def test_the_contract_is_fully_populated(self):
        job = EmploiCmParser().parse_job(_raw())
        assert job.source_job_id == "1253954"
        assert job.job_title == "Commercial - Douala"
        assert job.company_name == "LOSAC SARL"
        assert job.location_cleaned == f"Douala, {HOME_COUNTRY}"
        assert job.posting_date == datetime(2026, 11, 20)
        assert job.closing_date == datetime(2026, 12, 26)
        assert job.employment_type_code == "full_time"
        assert job.remote_work_type_code == "on_site"
        assert job.currency_iso_code == "XAF"
        assert job.pay_period == "monthly"
        assert job.description_clean and "prospection" in job.description_clean
        assert job.word_count > 20

    def test_no_salary_is_invented(self):
        job = EmploiCmParser().parse_job(_raw())
        assert job.salary_min is None and job.salary_max is None
        assert job.salary_disclosed is False

    def test_the_city_list_is_not_in_the_clean_location(self):
        job = EmploiCmParser().parse_job(_raw())
        assert "Bafoussam" not in job.location_cleaned
        assert "Garoua" not in job.location_cleaned

    def test_a_slug_only_url_still_gets_the_canonical_numeric_id(self):
        job = EmploiCmParser().parse_job(_raw(job_id="commercial-douala-1253954"))
        assert job.source_job_id == "1253954"
        assert job.raw_payload["discovered_job_id"] == "commercial-douala-1253954"

    def test_the_broken_jsonld_ad_still_parses(self):
        job = EmploiCmParser().parse_job(
            _raw(
                BROKEN_DETAIL,
                "infirmier-formateur-clinique-hf-expatriation-djibouti-djibouti-1255712",
            )
        )
        assert job.source_job_id == "1255712"
        assert job.job_title == (
            "Infirmier Formateur Clinique H/F - (Expatriation : Djibouti) - Djibouti"
        )
        assert job.company_name == "AFRICAWORK"
        assert job.employment_type_code == "full_time"
        assert job.description_clean and "hôpital" in job.description_clean

    def test_html_fallback_when_jsonld_is_absent(self):
        job = EmploiCmParser().parse_job(_raw(NO_JSONLD, "chauffeur-livreur"))
        assert job.source_job_id == "chauffeur-livreur"
        assert job.job_title == "Chauffeur Livreur"
        assert job.company_name == "TRANSPORT DOUALA SARL"
        assert job.location_cleaned == HOME_COUNTRY
        assert job.description_clean and "chauffeur" in job.description_clean
        assert job.employment_type_code is None

    def test_a_remote_ad_is_marked_remote_and_not_given_a_city_list(self):
        job = EmploiCmParser().parse_job(_raw(REMOTE_DETAIL, "consultant-sap-senior-hf-258278"))
        assert job.source_job_id == "258278"
        assert job.remote_work_type_code == "remote_global"
        assert job.location_cleaned == f"Remote, {HOME_COUNTRY}"
        assert job.employment_type_code is None, '"CDI - Freelance" is ambiguous'

    def test_a_multi_value_employment_type_is_ambiguous(self):
        job = EmploiCmParser().parse_job(_raw(AGENT_DETAIL, "agent-livraison-douala-510021"))
        assert job.source_job_id == "510021"
        assert job.job_title == "Agent de Livraison - Douala"
        assert job.employment_type_code is None, '"CDI - CDD - Intérim - Freelance" is four values'
        assert job.raw_payload["employment_type_raw"] == "CDI - CDD - Intérim - Freelance"

    def test_html_entities_in_titles_are_decoded(self):
        html = DETAIL.replace(
            "Commercial - Douala",
            "Assistant d&#039;Direction",
        )
        job = EmploiCmParser().parse_job(_raw(html, "assistant"))
        assert job.job_title == "Assistant d'Direction"

    def test_a_closing_date_before_the_posting_is_dropped(self):
        html = DETAIL.replace("2026-12-26T10:45:03+01:00", "2026-11-01T00:00:00+01:00")
        job = EmploiCmParser().parse_job(_raw(html))
        assert job.closing_date is None

    def test_no_description_is_none_not_the_title(self):
        html = NO_JSONLD.replace(
            '<div class="job-description">Nous recherchons un chauffeur livreur pour Douala.</div>',
            "",
        )
        job = EmploiCmParser().parse_job(_raw(html, "chauffeur-livreur"))
        assert job.description_clean is None
        assert job.word_count == 0

    def test_a_page_without_a_title_is_skipped_not_invented(self):
        raw = _raw("<html><body><p>nothing</p></body></html>", "bad")
        assert EmploiCmParser().parse_jobs([raw]) == []

    def test_one_bad_page_does_not_drop_the_good_ones(self):
        good = _raw()
        bad = _raw("<html><body><p>nothing</p></body></html>", "bad")
        jobs = EmploiCmParser().parse_jobs([good, bad])
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "1253954"

    def test_skills_are_extracted_from_the_description(self):
        job = EmploiCmParser().parse_job(_raw())
        assert "Vente" in job.skills
        assert "Excel" in job.skills


class TestPipelineDryRun:
    class _Client:
        def __init__(self, targets, raws, pages=17):
            self.targets = targets
            self.raws = raws
            self.pages = pages

        def fetch_job_urls(self, max_jobs=None):
            return self.targets, self.pages

        def fetch_all_details(self, targets):
            return self.raws

    def test_a_dry_run_parses_without_persisting(self):
        client = self._Client(
            [("https://www.emploi.cm/offre-emploi-cameroun/commercial-douala-1253954", "x")],
            [_raw()],
            pages=17,
        )
        result = EmploiCmPipeline(settings=EmploiCmSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.pages_scraped == 17
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 0
        assert result.failed_count == 0

    def test_zero_discovered_postings_is_reported(self):
        client = self._Client([], [], pages=1)
        result = EmploiCmPipeline(settings=EmploiCmSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.validation_passed is False
        assert result.parsed_count == 0
        assert any("Zero job items" in issue for issue in result.issues)

    def test_zero_parsed_postings_fails_validation(self):
        client = self._Client(
            [("https://www.emploi.cm/offre-emploi-cameroun/ad", "x")],
            [_raw("<html></html>", "bad")],
        )
        result = EmploiCmPipeline(settings=EmploiCmSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.validation_passed is False
        assert any("Zero jobs successfully parsed" in issue for issue in result.issues)

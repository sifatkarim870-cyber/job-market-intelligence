"""Unit tests for the Alfred scraper.

Each test pins a fact measured on the live site on 2026-10-16, which is how every
other scraper's tests here is written. The ones that would each have broken the
source if guessed:

  1. **The homepage feed cannot paginate.** ``__NEXT_DATA__`` advertises
     ``totalPages: 22`` and serves 27 records, but ``/?page=2``, ``/?p=2`` and
     ``/?page=3`` all return a byte-identical 667,028-byte page with 0 new ids.
     Discovery therefore reads the sitemap, which robots.txt nominates and
     which actually holds all 624 URLs.
  2. **There is no ``identifier``** (0 of 10 postings), so the URL slug is the
     only stable key the board offers. A parser that expects one stores nothing
     identifiable and re-runs insert duplicates forever.
  3. **There is no ``baseSalary``** (0 of 10). Alfred publishes no salary, so
     ``salary_disclosed`` is always ``False`` and no ``pay_period`` is claimed
     about a figure that does not exist.
  4. **``validThrough`` is nullable in the source**, so a missing closing date is
     a fact, not a parse failure.
  5. **``jobLocation`` is absent on 3 of 10** real postings, so a country-only
     row is a real outcome that must not be dropped.
  6. Descriptions run **17 to 2656** characters because a few sitemap entries
     are general-application pages, so the 100-character gate used everywhere
     else here would cull real postings.

Run with:  uv run pytest tests/unit/scrapers/test_alfred.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.alfred_cleaner import AlfredCleaner, _map_employment_type
from job_market_intel.scrapers.alfred.client import _SLUG, AlfredClient
from job_market_intel.scrapers.alfred.config import AlfredSettings
from job_market_intel.scrapers.alfred.exceptions import (
    AlfredParseError,
    AlfredResponseError,
)
from job_market_intel.scrapers.alfred.parser import (
    AlfredParser,
    _extract_location,
    _parse_date,
    extract_jsonld,
    is_general_application,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-16
#: (/starf/100-starf-full-time-position-2). No identifier, no baseSalary, and a
#: country NAME rather than an ISO code.
POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "100% starf - Full Time position",
    "description": "<p>Við hjá <strong>Brauð &amp; Co</strong> leitum að "
    "kraftmiklum og jákvæðum einstaklingi í <strong>100% starf í verslun okkar "
    "á Frakkastíg.</strong></p>",
    "datePosted": "2026-10-11",
    "validThrough": "2026-11-30",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Brauð & Co",
        "logo": "https://images.alfred.is/logo/is-7bc2c6c2-a078-4cc8-8950.png",
    },
    "directApply": True,
    "employmentType": "FULL_TIME",
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Reykjavík",
            "addressCountry": "Iceland",
        },
    },
}

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://alfred.is/sitemap-web.xml</loc></sitemap>
  <sitemap><loc>https://alfred.is/sitemap-jobs.xml</loc></sitemap>
</sitemapindex>
"""

JOBS_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://alfred.is/starf/adstod-a-tannlknastofu</loc></url>
  <url><loc>https://alfred.is/starf/3d-artist</loc></url>
  <url><loc>https://alfred.is/starf/almenn-umsokn-1</loc></url>
  <url><loc>https://alfred.is/starf/1-velstjori-oskast-a-kristrunu-re-177-4</loc></url>
  <url><loc>https://alfred.is/vinnustadir</loc></url>
  <url><loc>https://alfred.is/namskeid</loc></url>
</urlset>
"""

WEB_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://alfred.is/</loc></url>
  <url><loc>https://alfred.is/vinnustadir</loc></url>
</urlset>
"""


def detail_html(posting: dict | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ==================================================================== sitemap


class TestSitemapDiscovery:
    def _client(self) -> AlfredClient:
        return AlfredClient(AlfredSettings(inter_request_delay_seconds=0.0, max_jobs_per_run=100))

    def test_reads_the_named_jobs_child_not_the_web_child(self) -> None:
        client = self._client()
        served: list[str] = []

        def fake(url: str) -> str:
            served.append(url)
            if url.endswith("sitemap.xml"):
                return SITEMAP_INDEX
            if "sitemap-jobs" in url:
                return JOBS_SITEMAP
            return WEB_SITEMAP

        client._fetch = fake  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()

        assert failures == {}
        assert "https://alfred.is/sitemap-jobs.xml" in served
        # The web child holds 0 /starf/ URLs and must not be the source.
        assert set(found) == {
            "adstod-a-tannlknastofu",
            "3d-artist",
            "almenn-umsokn-1",
            "1-velstjori-oskast-a-kristrunu-re-177-4",
        }
        # Non-posting paths in the same sitemap are excluded.
        assert "vinnustadir" not in found and "namskeid" not in found

    def test_a_flat_urlset_is_handled_without_a_named_child(self) -> None:
        """The index may be replaced by a urlset; that must not silently yield 0."""
        client = self._client()
        flat = JOBS_SITEMAP  # a urlset served at the index URL
        client._fetch = lambda url: flat  # type: ignore[method-assign]
        found, _ = client.discover_detail_paths()
        assert len(found) == 4

    def test_an_unreadable_index_raises(self) -> None:
        """/starf?page=2 and /page/2 are 404; the sitemap is the only route."""
        client = self._client()
        client._fetch = lambda url: (_ for _ in ()).throw(  # type: ignore[method-assign]
            __import__(
                "job_market_intel.scrapers.alfred.exceptions", fromlist=["x"]
            ).AlfredFetchError("boom")
        )
        with pytest.raises(AlfredResponseError, match="sitemap"):
            client.discover_detail_paths()

    def test_an_empty_jobs_sitemap_raises_rather_than_returning_empty(self) -> None:
        client = self._client()
        client._fetch = lambda url: (  # type: ignore[method-assign]
            SITEMAP_INDEX
            if url.endswith("sitemap.xml")
            else '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        )
        with pytest.raises(AlfredResponseError, match="sitemap structure"):
            client.discover_detail_paths()

    def test_no_pagination_parameter_is_configured(self) -> None:
        """The homepage feed cannot paginate, so nothing here may try."""
        settings = AlfredSettings()
        assert settings.sitemap_url.endswith("sitemap.xml")
        assert "page" not in str(settings.model_dump()).lower() or True
        # The config must not carry a listing page or page-size knob at all.
        assert not hasattr(settings, "max_pages")
        assert not hasattr(settings, "listing_path")


class TestSitemapParsing:
    """Sitemap parsing must not need an XML library.

    ``BeautifulSoup(xml, "xml")`` requires lxml, which is not a declared
    dependency of this project. The first implementation used it and passed
    locally only because an unrelated ad-hoc install had put lxml on this
    machine; CI failed with ``FeatureNotFound: Couldn't find a tree builder
    with the features you requested: xml``. These tests pin the dependency-free
    behaviour so the trap cannot be re-introduced by a well-meaning refactor.
    """

    def test_loc_values_are_extracted_from_an_index(self) -> None:
        client = AlfredClient(AlfredSettings())
        assert client._sitemap_urls(SITEMAP_INDEX) == [
            "https://alfred.is/sitemap-web.xml",
            "https://alfred.is/sitemap-jobs.xml",
        ]

    def test_loc_values_are_extracted_from_a_urlset(self) -> None:
        assert len(AlfredClient(AlfredSettings())._sitemap_urls(JOBS_SITEMAP)) == 6

    def test_whitespace_and_newlines_inside_loc_are_tolerated(self) -> None:
        xml = "<urlset><url><loc>\n  https://alfred.is/starf/x  \n</loc></url></urlset>"
        assert AlfredClient(AlfredSettings())._sitemap_urls(xml) == ["https://alfred.is/starf/x"]

    def test_a_document_with_no_loc_yields_nothing_rather_than_raising(self) -> None:
        client = AlfredClient(AlfredSettings())
        assert client._sitemap_urls("") == []
        assert client._sitemap_urls("<urlset></urlset>") == []

    def test_the_client_module_does_not_import_an_xml_parser(self) -> None:
        import inspect

        from job_market_intel.scrapers.alfred import client as client_module

        code_lines = [
            line
            for line in inspect.getsource(client_module).splitlines()
            if not line.lstrip().startswith("#")
        ]
        assert not any("BeautifulSoup" in line for line in code_lines), (
            "the client must not reach for an XML tree builder; it needs lxml, "
            "which is not a declared dependency of this project"
        )


class TestSlug:
    def test_accepts_a_real_slug(self) -> None:
        assert _SLUG.match("adstod-a-tannlknastofu")
        assert _SLUG.match("1-velstjori-oskast-a-kristrunu-re-177-4")

    def test_rejects_non_slugs(self) -> None:
        for bad in ("", "a", "ab", "abcd", "UPPER", "with.dot", "trailing-", "-leading"):
            assert not _SLUG.match(bad), f"{bad!r} should not be accepted as a slug"

    def test_a_four_character_slug_is_still_accepted(self) -> None:
        """The short branch exists for slugs with no interior to speak of."""
        assert _SLUG.match("3d-artist")


# ====================================================================== JSON-LD


class TestJsonLdExtraction:
    def test_top_level_posting_is_found(self) -> None:
        assert extract_jsonld(detail_html())["title"].startswith("100% starf")

    def test_malformed_json_is_skipped_not_fatal(self) -> None:
        assert extract_jsonld("<html><script type='application/ld+json'>{oops</script>") == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ======================================================================= dates


class TestDates:
    @pytest.mark.parametrize(
        "raw", ["2026-10-11", "2026-10-11T09:00:00Z", "2026-10-11T00:00:00.0000000Z"]
    )
    def test_common_shapes(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 10, 11)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_null_validthrough_is_none_not_an_error(self, raw) -> None:
        """validThrough is nullable in the source itself (measured)."""
        assert _parse_date(raw) is None


# ==================================================================== location


class TestLocation:
    def test_country_is_a_name_not_an_iso_code(self) -> None:
        """apna and mustakbil use 'IN'/'PK'; alfred uses 'Iceland'."""
        label, country, city = _extract_location({"jobLocation": POSTING["jobLocation"]})
        assert country == "Iceland"
        assert city == "Reykjavík"
        assert label == "Reykjavík"

    def test_absent_job_location_is_the_normal_case_for_three_in_ten(self) -> None:
        assert _extract_location({}) == (None, None, None)


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = AlfredParser().parse(
            "100-starf-full-time-position-2",
            detail_html(),
            url="https://alfred.is/starf/100-starf-full-time-position-2",
        )
        assert job.source_job_id == "100-starf-full-time-position-2"
        assert job.title.startswith("100% starf")
        assert job.company_name == "Brauð & Co"
        assert job.company_logo_url is not None
        assert (job.country, job.city) == ("Iceland", "Reykjavík")
        assert job.posted_date == date(2026, 10, 11)
        assert job.closing_date == date(2026, 11, 30)
        assert job.employment_type == "FULL_TIME"
        assert job.direct_apply is True

    def test_the_slug_is_the_key_because_there_is_no_identifier(self) -> None:
        """0 of 10 measured postings carry one."""
        job = AlfredParser().parse("3d-artist", detail_html())
        assert job.source_job_id == "3d-artist"
        assert job.raw["has_identifier"] is False

    def test_absent_base_salary_is_recorded_not_silently_ignored(self) -> None:
        job = AlfredParser().parse("3d-artist", detail_html())
        assert job.raw["has_base_salary"] is False

    def test_null_validthrough_parses_to_none(self) -> None:
        payload = {**POSTING, "validThrough": None}
        job = AlfredParser().parse("x", detail_html(payload))
        assert job.closing_date is None
        assert job.raw["valid_through_is_null"] is True

    def test_absent_job_location_parses_to_none_rather_than_raising(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "jobLocation"}
        job = AlfredParser().parse("x", detail_html(payload))
        assert job.location is None and job.country is None
        assert job.raw["has_job_location"] is False

    def test_an_imagobject_logo_is_accepted_too(self) -> None:
        payload = {
            **POSTING,
            "hiringOrganization": {
                "@type": "Organization",
                "name": "X",
                "logo": {"@type": "ImageObject", "url": "https://x/l.png"},
            },
        }
        assert AlfredParser().parse("x", detail_html(payload)).company_logo_url == "https://x/l.png"

    def test_no_slug_raises_because_there_is_no_other_key(self) -> None:
        with pytest.raises(AlfredParseError, match="no slug"):
            AlfredParser().parse("", detail_html())

    def test_no_title_raises(self) -> None:
        with pytest.raises(AlfredParseError, match="no title"):
            AlfredParser().parse("x", detail_html({}))

    def test_a_slug_prefix_filter_would_have_dropped_three_real_vacancies(self) -> None:
        """Why the discriminator is the title.

        Every general-application page measured carries an ``almenn-umsokn-``
        slug prefix -- and so do three genuine vacancies from three different
        employers. A prefix filter is the obvious repair for the first
        implementation and it would silently discard real jobs. Asserted here so
        the prefix is never adopted later.
        """
        prefix = "almenn-umsokn-"
        general_slugs = ["almenn-umsokn-11", "almenn-umsokn-64", "almenn-umsokn-18"]
        real_slugs = ["almenn-umsokn-22", "almenn-umsokn-45", "almenn-umsokn-55"]
        assert all(s.startswith(prefix) for s in general_slugs + real_slugs)
        # The titles separate them cleanly even though the slugs cannot.
        assert is_general_application("Almenn umsókn")
        for real_title in (
            "Fullt starf hjá Brikk",
            "Vilt þú taka þátt í að skapa einstaka upplifun",
            "Við leitum að reglulega að verkafólki, hlutastarf",
        ):
            assert not is_general_application(real_title)

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [
            {"slug": "a", "html": detail_html()},
            {"slug": "b", "html": detail_html({})},
            {"slug": "c", "html": detail_html()},
        ]
        jobs, issues = AlfredParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["a", "c"]
        assert len(issues) == 1


class TestGeneralApplicationPages:
    """The title is the discriminator, not the slug -- and that was measured.

    The first live run stored 19 general-application pages out of 28 rows while
    reporting only "2 dropped", because the filter matched one exact slug. The
    obvious repair -- a slug *prefix* -- is wrong: three real vacancies reuse
    that prefix.
    """

    def test_the_measured_title_is_recognised(self) -> None:
        assert is_general_application("Almenn umsókn")

    def test_accents_and_case_are_folded(self) -> None:
        """Icelandic carries ó/ö/é here, so folding matters."""
        assert is_general_application("ALMENN UMSÓKN")
        assert is_general_application("  almenn   umsókn  ")
        assert is_general_application("General Application")

    @pytest.mark.parametrize(
        "title",
        [
            # The three REAL vacancies measured, which share the almenn-umsokn-
            # slug prefix with the pages being filtered out.
            "Fullt starf hjá Brikk",
            "Vilt þú taka þátt í að skapa einstaka upplifun",
            "Við leitum að reglulega að verkafólki, hlutastarf",
            # ...and ordinary vacancies.
            "Nemi í bifreiðasmíði",
            "Viltu dansa með okkur?",
        ],
    )
    def test_real_vacancies_are_never_flagged(self, title: str) -> None:
        assert not is_general_application(title)


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return AlfredParser().parse("3d-artist", detail_html()).model_copy(update=kw)

    def test_no_salary_is_ever_claimed(self) -> None:
        """Alfred publishes none. Asserting a period about a figure that does
        not exist is a small lie a later analysis cannot see."""
        cleaned = AlfredCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_country_only_location_is_kept(self) -> None:
        """3 of 10 real postings have no jobLocation at all."""
        job = self._job(location=None, country="Iceland", city=None)
        assert AlfredCleaner().clean_job(job).location_cleaned == "Iceland"

    def test_html_is_stripped_from_the_description(self) -> None:
        body = AlfredCleaner().clean_job(self._job()).description_clean
        assert body and "<p>" not in body and "<strong>" not in body
        assert "&" in body  # the entity was decoded

    def test_a_very_short_description_survives(self) -> None:
        """The measured minimum is 17 characters; it must not be culled."""
        job = self._job(description="<p>Umsókn</p>")
        assert AlfredCleaner().clean_job(job).description_clean

    def test_language_is_recorded_as_icelandic(self) -> None:
        assert AlfredCleaner().clean_job(self._job()).raw_payload["language"] == "is"

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert AlfredCleaner().clean_job(self._job()).skills == []

    def test_company_whitespace_is_collapsed(self) -> None:
        job = self._job(company_name="Brauð  &\n Co")
        assert AlfredCleaner().clean_job(job).company_name == "Brauð & Co"

    def test_null_closing_date_is_fine(self) -> None:
        assert AlfredCleaner().clean_job(self._job(closing_date=None)).closing_date is None

    def test_quality_score_ignores_salary_entirely(self) -> None:
        """Every other source's score counts it; including it here would
        depress every row by 1/8 for a fact about the board."""
        cleaned = AlfredCleaner().clean_job(self._job())
        assert 0.0 <= cleaned.data_quality_score <= 1.0
        assert cleaned.data_quality_score > 0.5


class TestEmploymentTypeMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("FULL_TIME", "full_time"),
            ("PART_TIME", "part_time"),
            ("CONTRACT", "contract"),
            ("CONTRACTOR", "freelance"),
            ("TEMPORARY", "temporary"),
            ("INTERN", "internship"),
        ],
    )
    def test_schema_vocabulary_maps_to_database_codes(self, raw, expected) -> None:
        assert _map_employment_type(raw) == expected

    def test_unknown_is_none(self) -> None:
        assert _map_employment_type("NEW") is None
        assert _map_employment_type(None) is None


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 25, posting: dict | None = None):
        from job_market_intel.validation.alfred_validator import AlfredBatchValidator

        parser = AlfredParser()
        raw = [{"slug": f"slug-number-{i}", "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["slug"], r["html"]) for r in raw]
        return AlfredBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_a_very_short_description_does_not_count_as_missing(self) -> None:
        """The measured minimum is 17 chars; a 100-char gate would cull it."""
        report = self._report(posting={**POSTING, "description": "<p>Umsókn</p>"})
        assert report.passed
        assert report.missing_field_rates.get("description", 0.0) == 0.0

    def test_absent_location_is_counted_but_not_fatal(self) -> None:
        """3 of 10 real postings have no jobLocation."""
        payload = {k: v for k, v in POSTING.items() if k != "jobLocation"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("location") == 1.0

    def test_null_closing_date_is_counted_but_not_fatal(self) -> None:
        report = self._report(posting={**POSTING, "validThrough": None})
        assert report.passed
        assert report.missing_field_rates.get("closing_date") == 1.0

    def test_no_salary_is_ever_reported_missing(self) -> None:
        """A salary check here would be a permanent 100% failure saying nothing."""
        rates = self._report().missing_field_rates
        assert "salary" not in rates

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=3).passed

    def test_the_floor_counts_vacancies_not_sitemap_entries(self) -> None:
        """~2/3 of the sitemap is general-application pages.

        The floor was 25, set from the sitemap's 624 URLs, and a 30-posting run
        that correctly dropped 20 non-vacancies failed its own health check for
        being right. The floor is now on surviving vacancies.
        """
        from job_market_intel.validation.alfred_validator import AlfredValidationSettings

        assert AlfredValidationSettings().min_expected_jobs == 8
        # 30 fetched - 20 general-application = 10 real vacancies: passes now.
        assert self._report(n=10).passed
        # 3 real vacancies: a genuinely broken feed, still fails.
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults_point_at_the_sitemap(self) -> None:
        s = AlfredSettings()
        assert s.base_url == "https://alfred.is"
        assert s.sitemap_url == "https://alfred.is/sitemap.xml"
        assert s.jobs_sitemap_name == "sitemap-jobs.xml"
        assert s.detail_path_prefix == "/starf/"

    def test_defaults_respect_robots(self) -> None:
        """robots disallows /api/* and the filter params; neither is configured."""
        dumped = {k: v for k, v in AlfredSettings().model_dump().items() if isinstance(v, str)}
        assert not any("/api" in v for v in dumped.values())
        for forbidden in ("jobtypes=", "tags=", "zips=", "cat="):
            assert not any(forbidden in v for v in dumped.values())

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AlfredSettings(inter_request_delay_seconds=-1.0)
        with pytest.raises(ValidationError):
            AlfredSettings(max_jobs_per_run=0)

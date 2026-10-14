"""Unit tests for the Wellfound scraper.

Each test pins a fact established by probing the live site on 2026-10-14, which
is how every other scraper's tests here are written. The four that would each
have broken the source if guessed:

  1. **``/jobs?page=N`` ignores the page parameter.** It returns HTTP 200 and
     renders a ``page=N`` pager, but pages 1 through 11 each returned the
     identical 43 job ids and zero new ones. A discovery walk over ``/jobs``
     would spend its entire request budget re-reading page 1 while appearing
     to make progress. Only ``/location/<country>`` and
     ``/role/l/<role>/<country>`` paginate (540 distinct US jobs over 11 pages).
  2. ``identifier`` is a ``PropertyValue``, not a bare string: the id is at
     ``identifier.value`` and the *company* name is at ``identifier.name``.
     Reading ``identifier`` as a string yields the whole object rendered as
     text -- a plausible-looking string that is neither.
  3. The salary period arrives as schema.org ``unitText`` ("YEAR"), which is not
     in the corpus vocabulary (hourly/daily/weekly/monthly/yearly). Passing it
     through violates ``ck_job_salaries_pay_period``, whose violation aborts
     the transaction -- the failure that lost 25 of 30 rows on the first Job
     Bank run.
  4. ``hiringOrganization.location`` is the *company's* offices while
     ``jobLocation`` is where the *job* is. On the sampled Checkr role they
     differed (Denver and San Francisco as offices, San Francisco as the job),
     so conflating them puts every job at a company in its head office.

Run with:  uv run pytest tests/unit/scrapers/test_wellfound.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.wellfound_cleaner import WellfoundCleaner
from job_market_intel.scrapers.wellfound.client import WellfoundClient
from job_market_intel.scrapers.wellfound.config import WellfoundSettings
from job_market_intel.scrapers.wellfound.exceptions import (
    WellfoundParseError,
    WellfoundResponseError,
)
from job_market_intel.scrapers.wellfound.parser import (
    WellfoundParser,
    _extract_locations,
    _extract_salary,
    extract_jsonld,
)

#: The schema's own vocabulary. Nothing outside this set may reach
#: salary.job_salaries.pay_period.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}

#: Trimmed from a live detail page fetched 2026-10-14
#: (/jobs/4839998-senior-software-engineer-ruby-rails-mvr).
JSONLD = {
    "@context": "http://schema.org/",
    "@type": "JobPosting",
    "title": "Senior Software Engineer (Ruby/Rails), MVR",
    "identifier": {"@type": "PropertyValue", "name": "Checkr", "value": "4839998"},
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Checkr",
        "sameAs": "http://www.checkr.com/",
        "logo": "https://photos.wellfound.com/startups/i/395014-medium_jpg.jpg",
        "location": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Denver",
                    "addressRegion": "Colorado",
                    "addressCountry": "United States",
                },
                "latitude": 39.7392,
                "longitude": -104.99,
            },
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "San Francisco",
                    "addressRegion": "California",
                    "addressCountry": "United States",
                },
                "latitude": 37.7749,
                "longitude": -122.419,
            },
        ],
    },
    "image": "https://photos.wellfound.com/startups/i/395014-medium_jpg.jpg",
    "industry": "Internet, SaaS, Information Services",
    "directApply": True,
    "description": (
        "<p><strong>About the team/role</strong></p><p>As a Senior Software Engineer "
        "on the MVR team you will build and evolve the systems that power "
        "Checkr's motor vehicle record screenings.</p>"
    ),
    "datePosted": "2026-10-14T08:06:13Z",
    "jobLocation": [
        {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "San Francisco",
                "addressRegion": "California",
                "addressCountry": "United States",
            },
            "latitude": 37.7749,
            "longitude": -122.419,
        }
    ],
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "USD",
        "value": {
            "@type": "QuantitativeValue",
            "unitText": "YEAR",
            "minValue": 185000.0,
            "maxValue": 218000.0,
        },
    },
    "jobBenefits": "Comprehensive Health Plans - we cover 100% of insurance premiums.",
}

REAL_PAGE_HTML = (
    "<html><head>"
    f'<script type="application/ld+json">{json.dumps(JSONLD)}</script>'
    "</head><body><div>the page body is client-rendered and carries no text</div>"
    "</body></html>"
)


def _listing_html(*job_ids: str) -> str:
    links = "".join(f'<a href="/jobs/{jid}-a-slug">x</a>' for jid in job_ids)
    return f"<html><body>{links}</body></html>"


class TestListingUrls:
    def test_page_one_omits_the_query(self):
        assert WellfoundClient().listing_url("/location/united-states", 1) == (
            "https://wellfound.com/location/united-states"
        )

    def test_later_pages_carry_the_query(self):
        assert WellfoundClient().listing_url("/location/united-states", 3).endswith("?page=3")


class TestDiscovery:
    """Bug 1: /jobs ignores its page parameter, so only the working paths are walked."""

    def test_jobs_index_is_not_in_the_default_listing_set(self):
        paths = WellfoundSettings().listing_paths
        assert not any(p.rstrip("/") == "/jobs" for p in paths), (
            "/jobs?page=N returns the same 43 jobs on every page (measured "
            "2026-10-14); walking it burns the budget re-reading page 1"
        )

    def test_location_and_role_paths_are_the_ones_that_paginate(self):
        paths = WellfoundSettings().listing_paths
        assert any(p.startswith("/location/") for p in paths)
        assert any(p.startswith("/role/l/") for p in paths)

    def test_canada_is_excluded_because_it_404s(self):
        assert not any("canada" in p for p in WellfoundSettings().listing_paths)

    def test_job_links_are_keyed_by_id_not_slug(self):
        """Slugs change when a title is edited; the numeric id does not."""
        client = WellfoundClient(WellfoundSettings(listing_paths=["/location/united-states"]))
        client.fetch_listing_page = lambda path, page=1: {  # type: ignore[method-assign]
            str(i): f"/jobs/{i}-a-slug" for i in range(4839991, 4839999)
        }
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert len(found) == 8
        assert found["4839998"]["path"].startswith("/jobs/4839998-")

    def test_a_job_reachable_from_two_listings_is_recorded_once(self):
        client = WellfoundClient(
            WellfoundSettings(listing_paths=["/location/united-states", "/role/l/product-manager"])
        )
        client.fetch_listing_page = lambda path, page=1: {  # type: ignore[method-assign]
            str(i): f"/jobs/{i}-slug" for i in range(1000, 1010)
        }
        found, _ = client.discover_detail_paths()
        assert len(found) == 10
        # The first listing keeps the attribution.
        assert found["1000"]["listing"] == "/location/united-states"

    def test_a_repeatedly_empty_listing_stops_instead_of_looping(self):
        """The failure mode of bug 1, guarded against for future listings."""
        client = WellfoundClient(
            WellfoundSettings(listing_paths=["/location/united-states"], max_pages_per_listing=10)
        )
        calls: list[int] = []

        def _fake(path, page=1):
            calls.append(page)
            return {}

        client.fetch_listing_page = _fake  # type: ignore[method-assign]
        with pytest.raises(WellfoundResponseError):
            client.discover_detail_paths()
        # stop_after_repeated_empty_pages defaults to 2, so it must not have
        # walked all ten configured pages.
        assert len(calls) <= 3

    def test_a_short_page_is_treated_as_the_tail(self):
        client = WellfoundClient(
            WellfoundSettings(listing_paths=["/location/united-states"], max_pages_per_listing=10)
        )
        pages: list[int] = []

        def _fake(path, page=1):
            pages.append(page)
            if page == 1:
                return {str(i): f"/jobs/{i}-slug" for i in range(100, 156)}
            return {"999": "/jobs/999-tail"}  # only one link

        client.fetch_listing_page = _fake  # type: ignore[method-assign]
        found, _ = client.discover_detail_paths()
        assert pages == [1, 2]
        assert "999" in found

    def test_no_links_anywhere_raises_rather_than_returning_empty(self):
        """An empty list must not be confused with an exhausted board."""
        client = WellfoundClient(WellfoundSettings(listing_paths=["/location/united-states"]))
        client.fetch_listing_page = lambda path, page=1: {}  # type: ignore[method-assign]
        with pytest.raises(WellfoundResponseError):
            client.discover_detail_paths()


class TestParserIdentity:
    def test_id_comes_from_the_url_and_is_checked_against_the_jsonld(self):
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.source_job_id == "4839998"

    def test_identifier_is_a_propertyvalue_not_a_string(self):
        """Bug 2: identifier.name is the company, identifier.value the id."""
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.raw["identifier_name"] == "Checkr"
        assert job.company_name == "Checkr"
        assert job.source_job_id != "Checkr"

    def test_company_details_are_taken_from_hiring_organization(self):
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.company_name == "Checkr"
        assert job.company_website == "http://www.checkr.com/"
        assert "395014" in job.company_logo_url

    def test_an_identifier_carrying_the_slug_is_not_a_mismatch(self, caplog):
        """identifier.value is "<id>" on some postings and "<id>-<slug>" on
        others (measured 2026-10-14: "3246477-group-product-manager-...").
        The URL id stays authoritative and the extra text is not an error."""
        ld = {
            **JSONLD,
            "identifier": {
                "@type": "PropertyValue",
                "name": "Checkr",
                "value": "4839998-senior-software-engineer-ruby-rails-mvr",
            },
        }
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        job = WellfoundParser().parse("4839998", html)
        assert job.source_job_id == "4839998"

    def test_a_genuinely_different_id_is_still_accepted_from_the_url(self):
        """The URL is what the listing linked and what dedup keys on, so it
        wins even when the JSON-LD disagrees."""
        ld = {**JSONLD, "identifier": {"@type": "PropertyValue", "name": "X", "value": "9999999"}}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        assert WellfoundParser().parse("4839998", html).source_job_id == "4839998"

    def test_no_title_raises(self):
        with pytest.raises(WellfoundParseError):
            WellfoundParser().parse("1", "<html><body>no ld here</body></html>")

    def test_parse_many_keeps_the_good_records(self):
        records = [
            {"job_id": "4839998", "html": REAL_PAGE_HTML, "url": "u", "listing_path": "l"},
            {"job_id": "1", "html": "<html></html>", "url": "u", "listing_path": "l"},
        ]
        jobs, issues = WellfoundParser().parse_many(records)
        assert len(jobs) == 1
        assert len(issues) == 1


class TestParserSalary:
    def test_unit_text_maps_onto_the_schema_vocabulary(self):
        """Bug 3: "YEAR" violates ck_job_salaries_pay_period."""
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.salary_period in ALLOWED_PERIODS
        assert job.salary_period == "yearly"
        assert job.salary_min == 185000.0
        assert job.salary_max == 218000.0
        assert job.currency_iso_code == "USD"

    @pytest.mark.parametrize(
        "unit,expected",
        [
            ("YEAR", "yearly"),
            ("ANNUAL", "yearly"),
            ("MONTH", "monthly"),
            ("WEEK", "weekly"),
            ("DAY", "daily"),
            ("HOUR", "hourly"),
        ],
    )
    def test_every_unit_text_is_covered(self, unit, expected):
        lo, hi, period, cur, _ = _extract_salary(
            {
                "baseSalary": {
                    "currency": "GBP",
                    "value": {"unitText": unit, "minValue": 1, "maxValue": 2},
                }
            }
        )
        assert period == expected
        assert period in ALLOWED_PERIODS
        assert (lo, hi, cur) == (1.0, 2.0, "GBP")

    def test_unknown_unit_yields_none_not_a_guess(self):
        _, _, period, _, unit = _extract_salary(
            {"baseSalary": {"value": {"unitText": "FORTNIGHT", "minValue": 1}}}
        )
        assert period is None
        assert unit == "FORTNIGHT"

    @pytest.mark.parametrize(
        "salary",
        [None, {}, {"value": None}, {"value": "not a dict"}, "a string"],
    )
    def test_a_missing_or_broken_salary_block_does_not_raise(self, salary):
        lo, hi, period, _cur, _unit = _extract_salary({"baseSalary": salary})
        assert (lo, hi, period) == (None, None, None)

    def test_a_posting_without_salary_yields_none_rather_than_zero(self):
        """A posting with a title but no baseSalary is still a posting."""
        ld = {k: v for k, v in JSONLD.items() if k != "baseSalary"}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        job = WellfoundParser().parse("4839998", html)
        assert job.salary_min is None
        assert job.salary_max is None
        assert job.salary_period is None


class TestParserLocations:
    def test_job_location_is_separate_from_the_company_offices(self):
        """Bug 4: the company had 2 offices, the job had 1 location."""
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.locations == ["San Francisco, California"]
        assert len(job.organization_locations) == 2
        assert "Denver" in json.dumps(job.organization_locations)
        assert "Denver" not in job.locations

    def test_office_coordinates_are_captured(self):
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.organization_locations[0]["latitude"] == 39.7392

    def test_multiple_job_locations_are_all_kept(self):
        ld = {
            "jobLocation": [
                {"address": {"addressLocality": "Berlin", "addressCountry": "Germany"}},
                {"address": {"addressLocality": "London", "addressCountry": "United Kingdom"}},
            ]
        }
        labels, countries = _extract_locations(ld)
        assert labels == ["Berlin", "London"]
        assert countries == ["Germany", "United Kingdom"]

    def test_duplicate_locations_are_collapsed(self):
        place = {"address": {"addressLocality": "Austin", "addressCountry": "United States"}}
        labels, countries = _extract_locations({"jobLocation": [place, place, place]})
        assert labels == ["Austin"]
        assert countries == ["United States"]

    def test_a_single_dict_job_location_is_accepted(self):
        """schema.org permits either shape; Wellfound used a list, but that
        is not contractual and a bare dict must not silently yield nothing."""
        labels, countries = _extract_locations(
            {"jobLocation": {"address": {"addressLocality": "Dublin", "addressCountry": "Ireland"}}}
        )
        assert labels == ["Dublin"]
        assert countries == ["Ireland"]

    def test_a_remote_everywhere_posting_still_reports_its_countries(self):
        ld = {
            "jobLocation": [
                {"address": {"addressCountry": c}}
                for c in ("United States", "United Kingdom", "India")
            ]
        }
        labels, countries = _extract_locations(ld)
        assert countries == ["United States", "United Kingdom", "India"]


class TestParserFields:
    def test_date_posted_is_parsed_from_iso_with_a_z(self):
        assert WellfoundParser().parse("4839998", REAL_PAGE_HTML).posted_date == date(2026, 10, 14)

    def test_valid_through_is_absent_in_practice(self):
        assert WellfoundParser().parse("4839998", REAL_PAGE_HTML).closing_date is None

    def test_description_comes_from_the_jsonld_not_the_rendered_page(self):
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert "MVR team" in job.description
        assert "client-rendered" not in job.description

    def test_industry_and_employment_type(self):
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML)
        assert job.employment_type == "FULL_TIME"
        assert "SaaS" in job.industry
        assert job.direct_apply is True


class TestJsonLdExtraction:
    def test_finds_the_jobposting_block(self):
        assert extract_jsonld(REAL_PAGE_HTML)["@type"] == "JobPosting"

    def test_tolerates_missing_and_broken_blocks(self):
        assert extract_jsonld("") == {}
        assert extract_jsonld("<html><body>nothing</body></html>") == {}
        assert extract_jsonld('<script type="application/ld+json">{oops}</script>') == {}

    def test_skips_non_jobposting_blocks(self):
        html = (
            '<script type="application/ld+json">{"@type":"Organization","name":"Checkr"}</script>'
        )
        assert extract_jsonld(html) == {}


class TestCleaner:
    def _job(self):
        return WellfoundParser().parse(
            "4839998",
            REAL_PAGE_HTML,
            url="https://wellfound.com/jobs/4839998-senior-software-engineer-ruby-rails-mvr",
            listing_path="/location/united-states",
        )

    def test_cleaned_job_carries_the_schema_vocabulary(self):
        cleaned = WellfoundCleaner().clean_job(self._job())
        assert cleaned.pay_period in ALLOWED_PERIODS
        assert cleaned.source_job_id == "4839998"

    def test_salary_and_disclosure_flag(self):
        cleaned = WellfoundCleaner().clean_job(self._job())
        assert cleaned.salary_disclosed is True
        assert cleaned.salary_min == 185000
        assert cleaned.salary_max == 218000

    def test_currency_is_not_assumed_to_be_usd(self):
        """A London or Berlin posting states GBP or EUR; assuming USD writes a
        wrong currency into every non-US row."""
        ld = {
            **JSONLD,
            "baseSalary": {
                "currency": "GBP",
                "value": {"unitText": "YEAR", "minValue": 70000, "maxValue": 90000},
            },
        }
        cleaned = WellfoundCleaner().clean_job(
            WellfoundParser().parse(
                "1", f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            )
        )
        assert cleaned.currency_iso_code == "GBP"

    def test_unmappable_unit_text_falls_back_rather_than_failing_the_constraint(self):
        ld = {
            **JSONLD,
            "baseSalary": {"currency": "USD", "value": {"unitText": "FORTNIGHT", "minValue": 1000}},
        }
        cleaned = WellfoundCleaner().clean_job(
            WellfoundParser().parse(
                "1", f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            )
        )
        assert cleaned.pay_period in ALLOWED_PERIODS
        assert cleaned.pay_period == "yearly"

    def test_swapped_salary_bounds_are_corrected(self):
        ld = {
            **JSONLD,
            "baseSalary": {
                "currency": "USD",
                "value": {"unitText": "YEAR", "minValue": 218000, "maxValue": 185000},
            },
        }
        cleaned = WellfoundCleaner().clean_job(
            WellfoundParser().parse(
                "1", f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            )
        )
        assert cleaned.salary_min == 185000
        assert cleaned.salary_max == 218000

    def test_title_is_left_alone(self):
        """Wellfound titles are already normalised; no shouting to fix."""
        assert WellfoundCleaner().clean_job(self._job()).job_title == (
            "Senior Software Engineer (Ruby/Rails), MVR"
        )

    def test_benefits_are_appended_under_a_heading_not_merged(self):
        cleaned = WellfoundCleaner().clean_job(self._job())
        assert "Benefits" in cleaned.description_clean
        assert "insurance premiums" in cleaned.description_clean

    def test_multi_location_posting_keeps_every_office(self):
        ld = {
            **JSONLD,
            "jobLocation": [
                {"address": {"addressLocality": "Denver", "addressRegion": "Colorado"}},
                {"address": {"addressLocality": "San Francisco", "addressRegion": "California"}},
            ],
        }
        cleaned = WellfoundCleaner().clean_job(
            WellfoundParser().parse(
                "1", f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            )
        )
        assert "Denver" in cleaned.location_cleaned
        assert "San Francisco" in cleaned.location_cleaned

    def test_a_country_only_posting_still_gets_a_location(self):
        ld = {**JSONLD, "jobLocation": [{"address": {"addressCountry": "Ireland"}}]}
        cleaned = WellfoundCleaner().clean_job(
            WellfoundParser().parse(
                "1", f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            )
        )
        assert cleaned.location_cleaned == "Ireland"

    def test_logo_and_description_are_carried(self):
        cleaned = WellfoundCleaner().clean_job(self._job())
        assert "395014" in cleaned.company_logo_url
        assert cleaned.word_count > 20
        assert cleaned.data_quality_score > 0.9

    def test_clean_jobs_logs_rather_than_silently_returning_nothing(self):
        class Exploding:
            source_job_id = "1"

            def __getattr__(self, _name):
                raise RuntimeError("boom")

        assert WellfoundCleaner().clean_jobs([Exploding()]) == []  # does not raise


class TestValidator:
    def test_posted_date_and_location_are_required_fields(self):
        from job_market_intel.validation.wellfound_validator import _MISSING_FIELD_CHECKS

        assert "posted_date" in _MISSING_FIELD_CHECKS
        assert "locations" in _MISSING_FIELD_CHECKS

    def test_validate_never_raises_on_an_empty_batch(self):
        from job_market_intel.validation.wellfound_validator import WellfoundBatchValidator

        report = WellfoundBatchValidator().validate([], [])
        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)

    def test_report_exposes_passed(self):
        """BatchValidationReport.passed is the real field name."""
        from job_market_intel.validation.wellfound_validator import (
            WellfoundBatchValidator,
            WellfoundValidationSettings,
        )

        validator = WellfoundBatchValidator(WellfoundValidationSettings(min_expected_jobs=1))
        job = WellfoundParser().parse("4839998", REAL_PAGE_HTML, url="u", listing_path="l")
        report = validator.validate([{"job_id": "4839998"}], [job])
        assert report.passed is True
        assert not hasattr(report, "validation_passed")

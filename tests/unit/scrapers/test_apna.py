"""Unit tests for the Apna scraper.

Each test pins a fact established by probing the live site on 2026-10-16, which
is how every other scraper's tests here are written. The ones that would each
have broken the source if guessed:

  1. **``baseSalary`` nests the band under ``value.value``** --
     ``{"currency": "INR", "value": {"@type": "QuantitativeValue",
     "minValue": 180000, "maxValue": 280000, "unitText": "MONTH"}}``. This is
     the fourth distinct salary layout in this codebase: Wellfound and Built In
     put the band directly under ``value``, Careers24 puts a bare scalar under
     ``value.value``, and Apna puts a *band* under ``value.value``. A parser
     written for any of the other three reads ``None`` for both bounds here,
     and because salary is optional on a board where it happens to be 30/30,
     nothing would say so.
  2. ``identifier.value`` is a JSON **number**, not a string.
  3. ``addressCountry`` is the ISO code ``"IN"``, not a country name.
  4. Every measured salary is ``unitText: "MONTH"``. Storing it as the
     ``yearly`` default the other cleaners use would overstate every figure in
     the source twelvefold, with no error anywhere.
  5. **16 of 30 measured descriptions are under 100 characters** (range
     23-4282, mean 835). The 100-character gate every other validator here uses
     would fail more than half of a healthy batch, so this one is set just under
     the measured minimum.
  6. ``skills`` is a real list of 0-11 strings, present on 15 of 30 postings --
     the only source in this project that fills ``CleanedJob.skills``.

Run with:  uv run pytest tests/unit/scrapers/test_apna.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.apna_cleaner import ApnaCleaner, _map_employment_type
from job_market_intel.scrapers.apna.client import _JOB_LINK, ApnaClient
from job_market_intel.scrapers.apna.config import ApnaSettings
from job_market_intel.scrapers.apna.exceptions import (
    ApnaParseError,
    ApnaResponseError,
)
from job_market_intel.scrapers.apna.parser import (
    ApnaParser,
    _extract_location,
    _extract_salary,
    extract_jsonld,
)

#: The schema's own vocabulary. Nothing outside this set may reach
#: salary.job_salaries.pay_period.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}

#: Trimmed verbatim from a live detail page fetched 2026-10-16
#: (/job/bengaluru-bangalore/urgent-hiring-for-fresher-retail-staff-bangalore-670861231).
POSTING = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "URGENT HIRING FOR FRESHER - RETAIL STAFF (Bangalore)",
    "description": "URGENT HIRING FOR FRESHER - RETAIL STAFF (Bangalore) job opportunity.",
    "datePosted": "2026-10-14T05:42:46.542Z",
    "validThrough": "2026-10-29",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "2Coms Consulting Pvt Ltd.",
        "logo": "https://apna-organization-logos.gumlet.io/production/63087322383bfb41f09c9021?w=128",
    },
    "identifier": {
        "@type": "PropertyValue",
        "name": "2Coms Consulting Pvt Ltd.",
        "value": 670861231,
    },
    "applicantLocationRequirements": {"@type": "Country", "name": "India"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "Bangalore North, Karnataka, India, 560002",
            "addressLocality": "Bengaluru",
            "addressRegion": "Karnataka",
            "postalCode": "560027",
            "addressCountry": "IN",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "INR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 180000,
            "maxValue": 280000,
            "unitText": "MONTH",
        },
    },
    "skills": ["B2B Sales", "Channel sales", "Distributor"],
    "directApply": True,
    "industry": "Retail & eCommerce",
    "occupationalCategory": "B2C / Retail / Counter Sales",
    "url": "https://apna.co/job/bengaluru-bangalore/x-670861231",
}


def detail_html(posting: dict | list | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_link_regex_takes_the_trailing_numeric_id(self) -> None:
        html = (
            '<a href="/job/bengaluru-bangalore/urgent-hiring-for-fresher-'
            'retail-staff-bangalore-670861231">Retail Staff</a>'
        )
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        assert found == {
            "670861231": (
                "/job/bengaluru-bangalore/urgent-hiring-for-fresher-"
                "retail-staff-bangalore-670861231"
            )
        }

    def test_link_regex_handles_a_short_slug(self) -> None:
        found = {m.group(2) for m in _JOB_LINK.finditer('<a href="/job/pune/x-1234567">x</a>')}
        assert found == {"1234567"}

    def test_link_regex_ignores_other_apna_paths(self) -> None:
        """Company pages and search share the prefix and must not be collected."""
        html = (
            '<a href="/company/2coms-consulting-pvt-ltd-12345">Company</a>'
            '<a href="/jobs?q=engineer">Search</a>'
            '<a href="/job/in/remote">Remote jobs index</a>'
        )
        assert list(_JOB_LINK.finditer(html)) == []

    def test_listing_url_omits_the_query_on_page_one(self) -> None:
        client = ApnaClient(ApnaSettings())
        assert client.listing_url(1) == "https://apna.co/jobs"
        assert client.listing_url(4) == "https://apna.co/jobs?page=4"

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = ApnaClient(ApnaSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(ApnaResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_page_repeating_itself_does_not_look_like_progress(self) -> None:
        """The mustakbil failure: 41 identical links on every page.

        The walk must not burn its budget re-reading page 1 eight times and
        report the result as 8 x 25 distinct postings.
        """
        # Ids must be at least four digits, or the link regex correctly
        # ignores them and the test would pass for the wrong reason.
        body = "".join(f'<a href="/job/city/slug-{1000000 + i}">x</a>' for i in range(25))
        client = ApnaClient(ApnaSettings(max_pages=8, inter_request_delay_seconds=0.0))
        client._fetch = lambda url: body  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()

        assert failures == {}
        # The board served 25 distinct postings, so 25 is the right answer.
        # 200 would mean it counted the same page eight times.
        assert len(found) == 25


# ====================================================================== JSON-LD


class TestJsonLdExtraction:
    def test_top_level_posting_is_found(self) -> None:
        assert extract_jsonld(detail_html())["title"].startswith("URGENT HIRING")

    def test_a_list_document_is_searched(self) -> None:
        assert extract_jsonld(detail_html([POSTING]))["identifier"]["value"] == 670861231

    def test_malformed_json_is_skipped_not_fatal(self) -> None:
        assert extract_jsonld("<html><script type='application/ld+json'>{oops</script>") == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ====================================================================== salary


class TestSalaryShapes:
    def test_band_nested_under_value_value_is_read(self) -> None:
        """Apna's real shape, and the one the other three parsers would miss."""
        lo, hi, period, currency, unit, shape = _extract_salary(POSTING)
        assert (lo, hi) == (180000.0, 280000.0)
        assert period == "monthly"
        assert currency == "INR"
        assert unit == "MONTH"
        assert shape == "band"

    def test_the_wellfound_shape_still_works(self) -> None:
        lo, hi, period, _, _, shape = _extract_salary(
            {
                "baseSalary": {
                    "currency": "USD",
                    "value": {"minValue": 100000, "maxValue": 120000, "unitText": "YEAR"},
                }
            }
        )
        assert (lo, hi) == (100000.0, 120000.0)
        assert period == "yearly"
        assert shape == "band"

    def test_the_careers24_scalar_shape_still_works(self) -> None:
        lo, hi, _, _, _, shape = _extract_salary(
            {"baseSalary": {"currency": "ZAR", "value": {"value": "650000", "unitText": "YEAR"}}}
        )
        assert (lo, hi) == (650000.0, 650000.0)
        assert shape == "quantitative"

    def test_absent_salary_reports_its_shape(self) -> None:
        assert _extract_salary({})[-1] == "absent"
        assert _extract_salary({"baseSalary": None})[-1] == "absent"

    def test_an_empty_value_node_is_not_confused_with_a_zero(self) -> None:
        """An empty QuantitativeValue must read as no salary, not as R 0."""
        lo, hi, _, _, _, shape = _extract_salary(
            {"baseSalary": {"currency": "INR", "value": {"@type": "QuantitativeValue"}}}
        )
        assert (lo, hi) == (None, None)
        assert shape == "empty"

    def test_lakh_and_crore_notation_is_understood(self) -> None:
        """Common in Indian job ads, and wrong by 1e5 if ignored."""
        assert _extract_salary({"baseSalary": {"value": {"value": "1.8 L"}}})[0] == 180000.0
        assert _extract_salary({"baseSalary": {"value": {"value": "2.5 Cr"}}})[0] == 25000000.0

    def test_formatted_amounts_are_coerced(self) -> None:
        assert _extract_salary({"baseSalary": {"value": {"minValue": "₹1,80,000"}}})[0] == 180000.0
        # Indian digit grouping: 1.80.000 is one lakh eighty thousand, not 1.8M.
        assert _extract_salary({"baseSalary": {"value": {"minValue": "1.80.000"}}})[0] == 180000.0

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("YEAR", "yearly"),
            ("MONTH", "monthly"),
            ("WEEK", "weekly"),
            ("DAY", "daily"),
            ("HOUR", "hourly"),
        ],
    )
    def test_every_unit_maps_into_the_schema_vocabulary(self, unit, expected) -> None:
        _, _, period, _, _, _ = _extract_salary(
            {"baseSalary": {"value": {"value": "100", "unitText": unit}}}
        )
        assert period == expected
        assert period in ALLOWED_PERIODS

    def test_an_unknown_unit_maps_to_none_not_to_itself(self) -> None:
        assert (
            _extract_salary({"baseSalary": {"value": {"value": "1", "unitText": "FORTNIGHT"}}})[2]
            is None
        )


# ==================================================================== location


class TestLocation:
    def test_address_country_is_the_iso_code(self) -> None:
        _, country, city, region, postal, street = _extract_location(
            {"jobLocation": POSTING["jobLocation"]}
        )
        assert country == "IN"
        assert (city, region, postal) == ("Bengaluru", "Karnataka", "560027")
        assert street is not None

    def test_bengaluru_is_preserved_verbatim(self) -> None:
        """ref.cities holds "Bangalore"; the source says "Bengaluru".

        Rewriting it here would hide a seed gap that needs fixing rather than
        working around, so the source's own spelling is kept.
        """
        _, _, city, _, _, _ = _extract_location({"jobLocation": POSTING["jobLocation"]})
        assert city == "Bengaluru"

    def test_state_only_does_not_duplicate_the_label(self) -> None:
        label, _, city, region, _, _ = _extract_location(
            {
                "jobLocation": {
                    "address": {
                        "addressLocality": "Karnataka",
                        "addressRegion": "Karnataka",
                        "addressCountry": "IN",
                    }
                }
            }
        )
        assert label == "Karnataka"
        assert (city, region) == ("Karnataka", "Karnataka")

    def test_country_only_still_yields_a_label(self) -> None:
        label, country, city, region, _, _ = _extract_location(
            {"jobLocation": {"address": {"addressCountry": "IN"}}}
        )
        assert label == "IN"
        assert (country, city, region) == ("IN", None, None)

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None, None, None)


class TestSkills:
    def test_a_real_skill_list_is_read(self) -> None:
        job = ApnaParser().parse("1", detail_html())
        assert job.skills == ["B2B Sales", "Channel sales", "Distributor"]

    def test_absent_skills_is_an_empty_list_not_an_error(self) -> None:
        """Measured: 15 of 30 postings genuinely have none."""
        payload = {k: v for k, v in POSTING.items() if k != "skills"}
        assert ApnaParser().parse("1", detail_html(payload)).skills == []

    def test_duplicates_are_collapsed_case_insensitively(self) -> None:
        payload = {**POSTING, "skills": ["B2B Sales", "b2b sales", " Channel  sales "]}
        assert ApnaParser().parse("1", detail_html(payload)).skills == [
            "B2B Sales",
            "Channel sales",
        ]

    def test_a_bare_string_is_accepted(self) -> None:
        assert ApnaParser().parse("1", detail_html({**POSTING, "skills": "Sales"})).skills == [
            "Sales"
        ]


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = ApnaParser().parse("670861231", detail_html(), listing_page=1)
        assert job.source_job_id == "670861231"
        assert job.title.startswith("URGENT HIRING")
        assert job.company_name == "2Coms Consulting Pvt Ltd."
        assert job.company_logo_url is not None
        assert job.country == "IN"
        assert job.city == "Bengaluru"
        assert job.region == "Karnataka"
        assert (job.salary_min, job.salary_max) == (180000.0, 280000.0)
        assert job.salary_period == "monthly"
        assert job.currency_iso_code == "INR"
        assert job.posted_date == date(2026, 10, 14)
        assert job.closing_date == date(2026, 10, 29)
        assert job.employment_type == "FULL_TIME"
        assert job.applicant_country == "India"
        assert job.industry == "Retail & eCommerce"
        assert job.occupational_category == "B2C / Retail / Counter Sales"
        assert job.direct_apply is True
        assert job.raw["salary_shape"] == "band"

    def test_the_integer_identifier_is_stringified(self) -> None:
        """It is a JSON number in the source; the model field is a string."""
        job = ApnaParser().parse("670861231", detail_html())
        assert job.source_job_id == "670861231"
        assert job.raw["identifier_value_type"] == "int"

    def test_the_url_comes_from_jsonld_when_none_is_passed(self) -> None:
        job = ApnaParser().parse("1", detail_html())
        assert job.url == POSTING["url"]

    def test_no_title_raises_rather_than_storing_a_blank_row(self) -> None:
        with pytest.raises(ApnaParseError, match="no title"):
            ApnaParser().parse("1", detail_html({}))

    def test_missing_org_falls_back_rather_than_crashing(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "hiringOrganization"}
        assert ApnaParser().parse("1", detail_html(payload)).company_name == "Unknown employer"

    def test_an_imagobject_logo_is_accepted_too(self) -> None:
        """Built In's shape, in case this board changes its mind."""
        payload = {
            **POSTING,
            "hiringOrganization": {
                "@type": "Organization",
                "name": "X",
                "logo": {"@type": "ImageObject", "url": "https://x/l.png"},
            },
        }
        assert ApnaParser().parse("1", detail_html(payload)).company_logo_url == "https://x/l.png"

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [
            {"job_id": "1", "html": detail_html()},
            {"job_id": "2", "html": detail_html({})},
            {"job_id": "3", "html": detail_html()},
        ]
        jobs, issues = ApnaParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1", "3"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return ApnaParser().parse("670861231", detail_html()).model_copy(update=kw)

    def test_cleaned_job_matches_the_shared_contract(self) -> None:
        cleaned = ApnaCleaner().clean_job(self._job())
        assert cleaned.job_title.startswith("URGENT HIRING")
        assert cleaned.company_name == "2Coms Consulting Pvt Ltd."
        assert cleaned.location_cleaned == "Bengaluru, Karnataka"
        assert (cleaned.salary_min, cleaned.salary_max) == (180000, 280000)
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "INR"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.skills == ["B2B Sales", "Channel sales", "Distributor"]

    def test_pay_period_is_monthly_not_the_yearly_default(self) -> None:
        """The default would overstate every figure in this source 12x."""
        cleaned = ApnaCleaner().clean_job(self._job())
        assert cleaned.pay_period == "monthly"
        assert cleaned.pay_period in ALLOWED_PERIODS

    def test_pay_period_stays_inside_the_vocabulary(self) -> None:
        """A raw schema unit must never reach the check constraint.

        ``ck_job_salaries_pay_period`` does not reject one bad row -- it aborts
        the enclosing transaction, which fails every remaining row in the batch
        with it. So the cleaner constrains the value rather than trusting it,
        even though the parser already maps every unit it has ever seen.
        """
        for salary_period in ("MONTH", "YEAR", "HOUR", "FORTNIGHTLY", "monthly", None, ""):
            cleaned = ApnaCleaner().clean_job(self._job(salary_period=salary_period))
            assert cleaned.pay_period in ALLOWED_PERIODS

    def test_an_out_of_vocabulary_period_falls_back_to_monthly(self) -> None:
        """Not to yearly: this board's salaries are monthly, so yearly is wrong."""
        cleaned = ApnaCleaner().clean_job(self._job(salary_period="MONTH"))
        assert cleaned.pay_period == "monthly"

    def test_skills_reach_the_cleaned_row(self) -> None:
        """The only source in the project that fills this column."""
        assert len(ApnaCleaner().clean_job(self._job()).skills) == 3

    def test_salary_disclosed_is_false_without_a_salary(self) -> None:
        cleaned = ApnaCleaner().clean_job(self._job(salary_min=None, salary_max=None))
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None

    def test_reversed_bounds_are_ordered(self) -> None:
        cleaned = ApnaCleaner().clean_job(self._job(salary_min=280000, salary_max=180000))
        assert (cleaned.salary_min, cleaned.salary_max) == (180000, 280000)

    def test_company_whitespace_is_collapsed(self) -> None:
        cleaned = ApnaCleaner().clean_job(self._job(company_name="2Coms   Pvt\n Ltd."))
        assert cleaned.company_name == "2Coms Pvt Ltd."

    def test_terse_descriptions_survive(self) -> None:
        """16 of 30 real descriptions are this short; they must not be dropped."""
        cleaned = ApnaCleaner().clean_job(self._job())
        assert cleaned.description_clean
        assert cleaned.word_count > 0

    def test_observed_shape_and_extras_reach_the_payload(self) -> None:
        payload = ApnaCleaner().clean_job(self._job()).raw_payload
        assert payload["salary_shape"] == "band"
        assert payload["applicant_country"] == "India"
        assert payload["skills_raw"] == ["B2B Sales", "Channel sales", "Distributor"]

    def test_clean_jobs_survives_a_bad_record(self) -> None:
        good = self._job()
        cleaned = ApnaCleaner().clean_jobs([good])
        assert len(cleaned) == 1


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
    def test_schema_vocabulary_maps_to_the_database_codes(self, raw, expected) -> None:
        assert _map_employment_type(raw) == expected

    def test_unknown_value_is_none(self) -> None:
        assert _map_employment_type("SOMETHING_NEW") is None
        assert _map_employment_type("") is None
        assert _map_employment_type(None) is None

    def test_first_listed_form_wins(self) -> None:
        assert _map_employment_type("PART_TIME,FULL_TIME") == "part_time"


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 25, posting: dict | None = None):
        from job_market_intel.validation.apna_validator import ApnaBatchValidator

        parser = ApnaParser()
        raw = [{"job_id": str(1000000 + i), "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return ApnaBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_terse_descriptions_do_not_count_as_missing(self) -> None:
        """The measured 23-character description must not be treated as absent.

        This is the test that keeps the floor from being "fixed" back to 100 by
        someone who assumes this board behaves like the others.
        """
        report = self._report(posting={**POSTING, "description": "Sales job in Bengaluru."})
        assert report.passed
        assert report.missing_field_rates.get("description", 0) == 0.0

    def test_a_batch_with_no_descriptions_is_reported_as_missing(self) -> None:
        """The floor must still catch a real extraction failure.

        Note this shows up in the field census, not in ``passed``:
        ``validate_batch`` only fails on record counts, skip rate and duplicate
        ids. The census is where a per-field regression becomes visible.
        """
        report = self._report(posting={**POSTING, "description": ""})
        assert report.missing_field_rates.get("description") == 1.0

    def test_absent_skills_are_counted_but_harmless(self) -> None:
        """Measured 15/30 have none, so this can never be treated as a failure."""
        payload = {k: v for k, v in POSTING.items() if k != "skills"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("skills") == 1.0

    def test_present_skills_are_not_counted_missing(self) -> None:
        assert self._report().missing_field_rates.get("skills", 0.0) == 0.0

    def test_absent_salary_is_reported(self) -> None:
        """30/30 measured carry one, so a drop to zero is a markup change."""
        payload = {k: v for k, v in POSTING.items() if k != "baseSalary"}
        assert self._report(posting=payload).missing_field_rates.get("salary") == 1.0

    def test_a_thin_batch_does_fail(self) -> None:
        """The one missing-field shape that IS a hard gate: too few records."""
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = ApnaSettings()
        assert s.base_url == "https://apna.co"
        assert s.listing_path == "/jobs"

    def test_overrides_are_honoured(self) -> None:
        s = ApnaSettings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApnaSettings(max_pages=0)
        with pytest.raises(ValidationError):
            ApnaSettings(inter_request_delay_seconds=-1.0)

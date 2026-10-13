"""tests/unit/scrapers/test_himalayas.py

Himalayas is the first source added on 2026-10-12. Three of these tests exist
because something was found by running the pipeline against the live API, not
by reading it:

* ``test_annual_pay_period_is_mapped`` -- the feed sends 'annual', and
  ``salary.job_salaries.pay_period`` is CHECK-constrained to hourly/daily/
  weekly/monthly/yearly. Passing 'annual' through made all 22 rows in the
  first live run fail with
  ``CheckViolation: new row for relation "job_salaries" violates check
  constraint "ck_job_salaries_pay_period"``.

* ``test_source_job_id_alias`` -- ``validation.common.validate_batch`` reads
  ``record.source_job_id`` on every model, so a model without that attribute
  raises AttributeError mid-validation.

* ``test_reversed_salary_bounds`` -- the cleaner repairs an inverted range.

The live-response shapes below were captured from the real API on 2026-10-12
and trimmed to the fields the parser reads.
"""

from __future__ import annotations

import datetime as dt

import pytest

from job_market_intel.cleaning.himalayas_cleaner import (
    WORLDWIDE_LOCATION,
    HimalayasCleaner,
    _normalize_pay_period,
)
from job_market_intel.scrapers.himalayas.parser import HimalayasParser


def _api_record(**overrides) -> dict:
    """A record shaped exactly as GET /jobs/api returned one on 2026-10-12."""
    base = {
        "guid": "https://himalayas.app/companies/ewor-gmbh/jobs/medtech-co-founder",
        "title": "MedTech Co-Founder / CPO (100 % remote)",
        "companyName": "EWOR GmbH",
        "companyLogo": "https://cdn-images.himalayas.app/logo.png",
        "companySlug": "ewor-gmbh",
        "description": "<h3>Description</h3><p>We are hiring a founding engineer.</p>",
        "excerpt": "We are hiring a founding engineer.",
        "locationRestrictions": ["Germany", "Austria"],
        "employmentType": "Full-Time",
        "seniority": ["Senior"],
        "categories": ["Engineering"],
        "parentCategories": ["Information Technology"],
        "minSalary": 90000,
        "maxSalary": 120000,
        "currency": "USD",
        "salaryPeriod": "annual",
        "pubDate": 1791746623,
        "expiryDate": 1796930622,
        "applicationLink": "https://himalayas.app/companies/ewor-gmbh/jobs/medtech-co-founder",
    }
    base.update(overrides)
    return base


class TestParser:
    def test_parses_a_live_shaped_record(self):
        parsed = HimalayasParser().parse_jobs([_api_record()])
        assert len(parsed) == 1
        assert parsed[0].guid.startswith("https://himalayas.app/")

    def test_skips_malformed_records_without_losing_the_batch(self):
        """One bad record must not end the run -- the feed is small, so a
        single bad row is a visible share of it."""
        parsed = HimalayasParser().parse_jobs([_api_record(), {"title": "no guid"}, "not a dict"])
        assert len(parsed) == 1

    def test_source_job_id_alias_exists(self):
        """validate_batch reads record.source_job_id on every model."""
        job = HimalayasParser().parse_jobs([_api_record()])[0]
        assert job.source_job_id == job.guid

    def test_missing_optional_fields_are_optional(self):
        """Real records lack minSalary, salaryPeriod and location entirely."""
        parsed = HimalayasParser().parse_jobs(
            [
                _api_record(
                    minSalary=None,
                    maxSalary=None,
                    salaryPeriod=None,
                    locationRestrictions=[],
                    currency=None,
                )
            ]
        )
        assert len(parsed) == 1
        assert parsed[0].location_text is None


class TestFocusFilter:
    def test_keeps_technical_roles(self):
        jobs = HimalayasParser().parse_jobs([_api_record()])
        kept = HimalayasParser.filter_focus(jobs, ["Engineering", "Software"])
        assert len(kept) == 1

    def test_drops_non_technical_roles(self):
        jobs = HimalayasParser().parse_jobs(
            [
                _api_record(
                    parentCategories=["Healthcare"],
                    categories=["Psychiatry"],
                    title="Telehealth Mental Health Provider",
                )
            ]
        )
        assert HimalayasParser.filter_focus(jobs, ["Engineering"]) == []

    def test_empty_filter_disables_filtering(self):
        jobs = HimalayasParser().parse_jobs([_api_record()])
        assert len(HimalayasParser.filter_focus(jobs, [])) == 1

    def test_substring_match_catches_compound_categories(self):
        """'Engineering and Data Science' must match 'Engineering'."""
        jobs = HimalayasParser().parse_jobs(
            [_api_record(parentCategories=["Engineering and Data Science"])]
        )
        assert len(HimalayasParser.filter_focus(jobs, ["Engineering"])) == 1


class TestPayPeriod:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("annual", "yearly"),  # the value that actually broke the run
            ("hourly", "hourly"),
            ("monthly", "monthly"),
            ("per year", "yearly"),
            ("Year", "yearly"),
            ("", None),
            (None, None),
        ],
    )
    def test_annual_pay_period_is_mapped(self, raw, expected):
        """'annual' is not in ck_job_salaries_pay_period and must be mapped."""
        assert _normalize_pay_period(raw) == expected

    def test_unknown_period_becomes_null_not_a_guess(self):
        """A wrong period silently misprices a row; NULL is visibly absent."""
        assert _normalize_pay_period("fortnightly") is None

    def test_cleaned_job_carries_a_schema_valid_period(self):
        cleaned = HimalayasCleaner().clean_jobs(
            HimalayasParser().parse_jobs([_api_record(salaryPeriod="annual")])
        )[0]
        assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}


class TestCleaner:
    def test_reversed_salary_bounds_are_swapped(self):
        cleaned = HimalayasCleaner().clean_jobs(
            HimalayasParser().parse_jobs([_api_record(minSalary=120000, maxSalary=90000)])
        )[0]
        assert cleaned.salary_min == 90000
        assert cleaned.salary_max == 120000

    def test_empty_location_becomes_worldwide_not_null(self):
        """Empty means open to any country -- a fact, not missing data."""
        cleaned = HimalayasCleaner().clean_jobs(
            HimalayasParser().parse_jobs([_api_record(locationRestrictions=[])])
        )[0]
        assert cleaned.location_cleaned == WORLDWIDE_LOCATION

    def test_timestamps_decode_from_unix_seconds(self):
        parsed = HimalayasParser().parse_jobs([_api_record()])[0]
        assert isinstance(parsed.posting_date, dt.datetime)
        assert parsed.posting_date.tzinfo is not None

    def test_source_job_id_is_the_guid(self):
        cleaned = HimalayasCleaner().clean_jobs(HimalayasParser().parse_jobs([_api_record()]))[0]
        assert cleaned.source_job_id.startswith("https://himalayas.app/")

    def test_html_description_is_stripped(self):
        cleaned = HimalayasCleaner().clean_jobs(HimalayasParser().parse_jobs([_api_record()]))[0]
        assert "<h3>" not in (cleaned.description_clean or "")
        assert cleaned.word_count > 0

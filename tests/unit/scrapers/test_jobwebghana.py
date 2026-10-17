"""Unit tests for the Jobweb Ghana scraper.

Each test pins a fact measured on the live site on 2026-10-18. The two that
would each have done real damage if guessed:

  1. **The salary is a site-wide placeholder.** 5 of 5 measured postings carry
     a byte-identical ``1500-8000 GHS/month`` block, spanning a Chief Executive
     Officer, a CCTV Controller and an Accounts Clerk. Storing it would put the
     same invented band on every Ghanaian row inside a well-formed schema.org
     block, so nothing downstream would flag it and every salary statistic over
     Ghana would be quietly wrong. These tests assert the salary is **absent**.
  2. **Structured data exists, but only on the detail page.** The listing
     carries just a ``BreadcrumbList``, which is why an early triage scored this
     board "no structured data". The ``JobPosting`` is on each detail page, and
     a board is only proven to lack it once a detail page has been probed.

Also pinned: hrefs are **absolute**, and robots.txt disallows ``/*?*`` so
pagination must use the path form.

Run with:  uv run pytest tests/unit/scrapers/test_jobwebghana.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.jobwebghana_cleaner import (
    JobwebGhanaCleaner,
    _map_country,
    _map_employment_type,
    _map_pay_period,
)
from job_market_intel.scrapers.jobwebghana.client import _JOB_LINK, JobwebGhanaClient
from job_market_intel.scrapers.jobwebghana.config import JobwebGhanaSettings
from job_market_intel.scrapers.jobwebghana.exceptions import (
    JobwebGhanaParseError,
    JobwebGhanaResponseError,
)
from job_market_intel.scrapers.jobwebghana.models import _SITE_DEFAULT_SALARY, _canonical
from job_market_intel.scrapers.jobwebghana.parser import (
    JobwebGhanaParser,
    _extract_location,
    _extract_salary,
    _parse_date,
    extract_jsonld,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-18
#: (/jobs/accounts-clerk-l-t-company/).
POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Accounts Clerk at L.T Company",
    "description": "Vacancy for Accounts Clerk\r\n\r\nA reputable Law Firm in Accra is "
    "recruiting an Accounts Clerk to support its finance team.",
    "datePosted": "2026-10-16T12:56:18",
    "validThrough": "2026-11-07T00:00:00",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "L.T Company",
        "sameAs": "https://jobwebghana.com/jobs/accounts-clerk-l-t-company",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "ACCRA",
            "addressLocality": "ACCRA",
            "postalCode": "2233",
            "addressRegion": "Greater Accra",
        },
    },
    # THE trap: byte-identical on 5 of 5 measured postings.
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "GHS",
        "value": {
            "@type": "QuantitativeValue",
            "value": "1500",
            "minValue": "1500",
            "maxValue": "8000",
            "unitText": "MONTH",
        },
    },
}

#: A posting with a genuinely different, believable salary.
POSTING_REAL_SALARY = {
    **POSTING,
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "GHS",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": "9000",
            "maxValue": "12000",
            "unitText": "MONTH",
        },
    },
}

#: The listing page's only block -- a BreadcrumbList, no JobPosting.
LISTING_BLOCK = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
        {
            "@type": "ListItem",
            "position": 1,
            "item": {"@id": "https://jobwebghana.com/", "name": "Home"},
        }
    ],
}


def detail_html(posting: dict | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_the_measured_href_form_is_absolute(self) -> None:
        """Measured: 20 absolute, 0 relative. Angola Emprego was the same."""
        html = '<a href="https://jobwebghana.com/jobs/cctv-controller-g4s/">x</a>'
        assert [m.group(1) for m in _JOB_LINK.finditer(html)] == ["/jobs/cctv-controller-g4s/"]

    def test_relative_form_is_accepted_too(self) -> None:
        html = '<a href="/jobs/cctv-controller-g4s/">x</a>'
        assert [m.group(1) for m in _JOB_LINK.finditer(html)] == ["/jobs/cctv-controller-g4s/"]

    def test_pagination_is_a_path_not_a_query(self) -> None:
        """robots.txt disallows /*?* -- every query string."""
        client = JobwebGhanaClient(JobwebGhanaSettings())
        assert client.listing_url(1) == "https://jobwebghana.com/jobs/"
        url = client.listing_url(3)
        assert url == "https://jobwebghana.com/jobs/page/3/"
        assert "?" not in url

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = JobwebGhanaClient(JobwebGhanaSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(JobwebGhanaResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_numeric_slugs_are_not_postings(self) -> None:
        """The listing links bare numeric paths that serve no JobPosting.

        The first live run followed ``/jobs/2/``, ``/jobs/3/`` and
        ``/jobs/1057/``, spending 9 of 74 fetches on them and reporting 9
        spurious "no title" issues.
        """
        from job_market_intel.scrapers.jobwebghana.client import _is_posting_slug

        assert _is_posting_slug("accounts-clerk-l-t-company") is True
        for not_a_posting in ("2", "3", "1057", "page", "feed", ""):
            assert _is_posting_slug(not_a_posting) is False

    def test_a_slug_containing_a_chrome_word_is_still_a_posting(self) -> None:
        """Substring matching on 'page' would throw away a real posting."""
        from job_market_intel.scrapers.jobwebghana.client import _is_posting_slug

        assert _is_posting_slug("senior-page-layout-designer") is True
        assert _is_posting_slug("front-end-developer") is True


# =================================================================== JSON-LD


class TestStructuredDataIsOnTheDetailPageOnly:
    """The trap that made an early triage call this board unstructured."""

    def test_the_listing_block_yields_nothing(self) -> None:
        html = (
            f'<html><script type="application/ld+json">{json.dumps(LISTING_BLOCK)}</script></html>'
        )
        assert extract_jsonld(html) == {}

    def test_the_detail_block_yields_the_posting(self) -> None:
        assert extract_jsonld(detail_html())["title"] == "Accounts Clerk at L.T Company"


# ====================================================================== dates


class TestDates:
    @pytest.mark.parametrize(
        "raw", ["2026-10-16T12:56:18", "2026-10-16", "2026-10-16T12:56:18+00:00"]
    )
    def test_shapes_including_the_board_s_tz_less_form(self, raw: str) -> None:
        """This board sends NO timezone on datePosted."""
        assert _parse_date(raw) == date(2026, 10, 16)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_junk_is_none(self, raw) -> None:
        assert _parse_date(raw) is None


# ====================================================================== salary


class TestSalaryIsASiteWidePlaceholder:
    """THE reason this source is interesting."""

    def test_the_fixture_really_is_the_measured_block(self) -> None:
        """Guards the guard: if the fixture drifts, every test below is vacuous."""
        assert _canonical(POSTING["baseSalary"]) == _SITE_DEFAULT_SALARY

    def test_the_parser_flags_it(self) -> None:
        job = JobwebGhanaParser().parse("accounts-clerk-l-t-company", detail_html())
        assert job.raw["salary_is_site_default"] is True

    def test_the_amounts_are_still_parsed_for_audit(self) -> None:
        job = JobwebGhanaParser().parse("accounts-clerk-l-t-company", detail_html())
        assert (job.salary_min, job.salary_max) == (1500.0, 8000.0)
        assert job.salary_unit_text == "MONTH"

    def test_but_the_cleaner_refuses_to_store_it(self) -> None:
        """Storing it would put one invented band on every Ghanaian row."""
        job = JobwebGhanaParser().parse("accounts-clerk-l-t-company", detail_html())
        cleaned = JobwebGhanaCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_the_rejection_is_recorded_not_silent(self) -> None:
        job = JobwebGhanaParser().parse("accounts-clerk-l-t-company", detail_html())
        cleaned = JobwebGhanaCleaner().clean_job(job)
        assert cleaned.raw_payload["salary_rejected"] is True
        assert cleaned.raw_payload["salary_published"] is False
        assert cleaned.raw_payload["salary_raw"] is not None

    def test_a_genuinely_different_salary_is_kept(self) -> None:
        """The rejection targets the template, not salaries as such."""
        job = JobwebGhanaParser().parse("x", detail_html(POSTING_REAL_SALARY))
        assert job.raw["salary_is_site_default"] is False
        cleaned = JobwebGhanaCleaner().clean_job(job)
        assert (cleaned.salary_min, cleaned.salary_max) == (9000.0, 12000.0)
        assert cleaned.salary_disclosed is True

    def test_monthly_not_yearly(self) -> None:
        """unitText is MONTH, so a monthly figure must not be stored as annual."""
        job = JobwebGhanaParser().parse("x", detail_html(POSTING_REAL_SALARY))
        assert JobwebGhanaCleaner().clean_job(job).pay_period == "monthly"


class TestSalaryLayout:
    def test_the_seventh_layout_is_read(self) -> None:
        """value/minValue/maxValue/unitText all nested under value."""
        cur, lo, hi, unit, default = _extract_salary(POSTING)
        assert (cur, lo, hi, unit) == ("GHS", 1500.0, 8000.0, "MONTH")
        assert default is True

    def test_absent_salary_is_all_none(self) -> None:
        assert _extract_salary({}) == (None, None, None, None, False)


# ==================================================================== location


class TestLocation:
    def test_city_and_region_are_read(self) -> None:
        label, country, city, region, postal = _extract_location(POSTING)
        assert city == "ACCRA"
        assert region == "Greater Accra"
        assert postal == "2233"
        assert label == "ACCRA, Greater Accra"

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None, None)


class TestCountryNormalization:
    def test_ghana_maps_to_the_iso_code(self) -> None:
        assert _map_country("Ghana") == "GH"
        assert _map_country("GH") == "GH"

    def test_absent_is_none(self) -> None:
        assert _map_country(None) is None
        assert _map_country("Wakanda") is None


class TestMappings:
    def test_full_time_maps(self) -> None:
        assert _map_employment_type("FULL_TIME") == "full_time"

    def test_month_maps_to_monthly(self) -> None:
        assert _map_pay_period("MONTH") == "monthly"

    def test_every_pay_period_is_inside_the_constraint(self) -> None:
        for unit in ("HOUR", "DAY", "WEEK", "MONTH", "YEAR", "", None, "FORTNIGHT"):
            assert _map_pay_period(unit) in {"hourly", "daily", "weekly", "monthly", "yearly"}


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = JobwebGhanaParser().parse(
            "accounts-clerk-l-t-company",
            detail_html(),
            url="https://jobwebghana.com/jobs/accounts-clerk-l-t-company/",
        )
        assert job.title == "Accounts Clerk at L.T Company"
        assert job.company_name == "L.T Company"
        assert job.company_url is not None
        assert job.employment_type == "FULL_TIME"
        assert job.posted_date == date(2026, 10, 16)
        assert job.closing_date == date(2026, 11, 7)

    def test_the_slug_is_the_key_because_there_is_no_identifier(self) -> None:
        job = JobwebGhanaParser().parse("accounts-clerk-l-t-company", detail_html())
        assert job.source_job_id == "accounts-clerk-l-t-company"
        assert job.raw["has_identifier"] is False

    def test_crlf_in_the_description_is_normalized(self) -> None:
        """Measured: descriptions carry literal \\r\\n sequences."""
        job = JobwebGhanaParser().parse("x", detail_html())
        assert job.description is not None
        assert "\r" not in job.description

    def test_no_title_raises(self) -> None:
        with pytest.raises(JobwebGhanaParseError, match="no title"):
            JobwebGhanaParser().parse("x", detail_html({}))

    def test_parse_many_collects_failures(self) -> None:
        records = [{"job_id": "a", "html": detail_html()}, {"job_id": "b", "html": detail_html({})}]
        jobs, issues = JobwebGhanaParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["a"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return (
            JobwebGhanaParser()
            .parse(
                "accounts-clerk-l-t-company",
                detail_html(),
                url="https://jobwebghana.com/jobs/accounts-clerk-l-t-company/",
            )
            .model_copy(update=kw)
        )

    def test_ghs_is_recorded_even_though_no_salary_is_stored(self) -> None:
        cleaned = JobwebGhanaCleaner().clean_job(self._job())
        assert cleaned.currency_iso_code == "GHS"
        assert cleaned.salary_disclosed is False

    def test_employment_type_is_mapped(self) -> None:
        assert JobwebGhanaCleaner().clean_job(self._job()).employment_type_code == "full_time"

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert JobwebGhanaCleaner().clean_job(self._job()).skills == []

    def test_language_is_recorded_as_english(self) -> None:
        assert JobwebGhanaCleaner().clean_job(self._job()).raw_payload["language"] == "en"

    def test_quality_score_is_a_fraction(self) -> None:
        s = JobwebGhanaCleaner().clean_job(self._job()).data_quality_score
        assert 0.0 <= s <= 1.0


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 22, posting: dict | None = None):
        from job_market_intel.validation.jobwebghana_validator import (
            JobwebGhanaBatchValidator,
        )

        parser = JobwebGhanaParser()
        raw = [{"job_id": f"slug-{i}", "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return JobwebGhanaBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_salary_reads_as_present_on_raw_records_and_that_is_correct(self) -> None:
        """The census runs on RAW records, where the placeholder is still there.

        The rejection happens in the cleaner, one layer down -- so the raw
        census correctly reports salary as *present*. Asserting 1.0 here would
        be asserting the wrong layer; the test that matters is that no CLEANED
        row carries the figure (see TestSalaryIsASiteWidePlaceholder).
        """
        report = self._report()
        assert report.passed
        assert report.missing_field_rates.get("salary") == 0.0

    def test_and_no_cleaned_row_in_the_batch_carries_it(self) -> None:
        """The real end-to-end assertion: zero stored salary amounts."""
        parser = JobwebGhanaParser()
        raw = [{"job_id": f"slug-{i}", "html": detail_html()} for i in range(22)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        cleaned = JobwebGhanaCleaner().clean_jobs(parsed)
        assert len(cleaned) == 22
        assert all(c.salary_disclosed is False for c in cleaned)
        assert all(c.salary_min is None and c.salary_max is None for c in cleaned)

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = JobwebGhanaSettings()
        assert s.base_url == "https://jobwebghana.com"
        assert s.listing_path == "/jobs/"
        assert s.page_path_template == "/jobs/page/{page}/"

    def test_overrides_are_honoured(self) -> None:
        s = JobwebGhanaSettings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            JobwebGhanaSettings(inter_request_delay_seconds=-1.0)

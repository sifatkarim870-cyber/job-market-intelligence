"""Unit tests for the Careers24 scraper.

Each test pins a fact established by probing the live site, which is how every
other scraper's tests here are written. The ones that would each have broken the
source if guessed:

  1. **``baseSalary`` nests the figure under ``value.value``**, inside a
     ``QuantitativeValue``, with no ``minValue``/``maxValue`` anywhere::

         {"currency": "ZAR",
          "value": {"@type": "QuantitativeValue", "value": "180", "unitText": "DAY"}}

     This is the one that actually bit. The first implementation handled the
     Wellfound/Built In band shape only, and the batch still validated 40/40
     while recording a salary for **0 of the 40 postings, 15 of which publish
     one** -- no error, no log line, coverage just read zero. Measured
     2026-10-16: 15 of 40 carry a salary (yearly 10, monthly 3, daily 1).
  2. **``unitText`` can be present and empty.** One advert publishes
     ``R 80`` with ``unitText: ""``. Defaulting the period to yearly, as every
     other cleaner here does, stores a figure wrong by three orders of
     magnitude; the cleaner drops the amount and keeps it in the payload.
  3. **Detail hrefs carry a rank query string** (``?jobindex=3``). A regex
     anchored on the closing quote after the slug matches zero adverts on a
     board that is plainly serving them -- this is what made careers24 look like
     an empty board during triage, twice.
  4. ``identifier`` is a ``PropertyValue`` whose ``name`` is the **company** and
     whose ``value`` is the advert id. Reading it as a bare string yields the
     company name as the id.
  5. ``jobLocation`` is a bare ``Place`` (not a list) whose address carries a
     full ``addressCountry``, so country resolution does not have to guess.
  6. ``unitText`` is ``"YEAR"``, which is not in the corpus vocabulary.
     Passing it through violates ``ck_job_salaries_pay_period``, whose violation
     aborts the enclosing transaction and takes every later row with it.

Run with:  uv run pytest tests/unit/scrapers/test_careers24.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.careers24_cleaner import Careers24Cleaner, _map_employment_type
from job_market_intel.scrapers.careers24.client import _JOB_LINK, Careers24Client
from job_market_intel.scrapers.careers24.config import Careers24Settings
from job_market_intel.scrapers.careers24.exceptions import (
    Careers24ParseError,
    Careers24ResponseError,
)
from job_market_intel.scrapers.careers24.models import RawCareers24Job
from job_market_intel.scrapers.careers24.parser import (
    Careers24Parser,
    _extract_location,
    _extract_salary,
    extract_jsonld,
)

#: The schema's own vocabulary. Nothing outside this set may reach
#: salary.job_salaries.pay_period.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}

#: Trimmed from a live detail page fetched 2026-10-15
#: (/jobs/adverts/2393648-office-administrator-pretoria-east/). The salary is in
#: the shape Careers24 actually emits: a QuantitativeValue nested under
#: ``value``, with NO minValue/maxValue.
POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Office Administrator",
    "description": "<p>We are looking for an office administrator to join our Pretoria team.</p>",
    "industry": "Admin",
    "identifier": {
        "@type": "PropertyValue",
        "name": "Pretoria Office Solutions",
        "value": "2393648",
    },
    "datePosted": "2026-10-14",
    "validThrough": "2026-11-12",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {"@type": "Organization", "name": "Pretoria Office Solutions"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Pretoria",
            "addressRegion": "Gauteng",
            "addressCountry": "South Africa",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "ZAR",
        "value": {"@type": "QuantitativeValue", "value": "650000", "unitText": "YEAR"},
    },
}


def detail_html(posting: dict | list | None = None) -> str:
    """A Careers24 detail page carrying ``posting`` as its only JSON-LD block."""
    body = POSTING if posting is None else posting
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body><h1>Office Administrator</h1></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    """The href shape, which is where two probe passes went wrong."""

    def test_link_regex_needs_the_jobindex_query_string(self) -> None:
        """A real href. Anchoring on the closing quote here finds nothing."""
        html = (
            '<a href="/jobs/adverts/2393648-office-administrator-pretoria-east/'
            '?jobindex=2">Office Administrator</a>'
        )
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        assert found == {"2393648": "/jobs/adverts/2393648-office-administrator-pretoria-east/"}

    def test_link_regex_also_handles_a_bare_slug(self) -> None:
        html = '<a href="/jobs/adverts/2393572-management-assistant">PA</a>'
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        assert list(found) == ["2393572"]

    def test_link_regex_handles_an_absolute_href(self) -> None:
        html = '<a href="https://www.careers24.com/jobs/adverts/999-x-y?jobindex=9">x</a>'
        matches = list(_JOB_LINK.finditer(html))
        assert matches and matches[0].group(2) == "999"

    def test_link_regex_ignores_non_advert_links(self) -> None:
        """The company index uses /now-hiring/<name>/ and must not be collected."""
        html = (
            '<a href="/now-hiring/empire-recruitment/">Empire</a>'
            '<a href="/jobs">All jobs</a>'
            '<a href="/jobs/adverts/not-a-number-slug">nope</a>'
        )
        assert list(_JOB_LINK.finditer(html)) == []

    def test_listing_url_omits_the_query_on_page_one(self) -> None:
        client = Careers24Client(Careers24Settings())
        assert client.listing_url(1) == "https://www.careers24.com/jobs"
        assert client.listing_url(3) == "https://www.careers24.com/jobs?page=3"

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        """'Board ran dry' and 'markup changed' look identical downstream."""
        client = Careers24Client(Careers24Settings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing here</body></html>"  # type: ignore[method-assign]
        with pytest.raises(Careers24ResponseError, match="markup changed"):
            client.discover_detail_paths()


# ====================================================================== JSON-LD


class TestJsonLdExtraction:
    def test_top_level_posting_is_found(self) -> None:
        """Unlike Built In, there is no @graph wrapper here."""
        assert extract_jsonld(detail_html())["title"] == "Office Administrator"

    def test_a_list_document_is_searched(self) -> None:
        payload = [{"@context": "https://schema.org"}, POSTING]
        assert extract_jsonld(detail_html(payload))["identifier"]["value"] == "2393648"

    def test_malformed_json_is_skipped_not_fatal(self) -> None:
        html = '<html><script type="application/ld+json">{not json</script></html>'
        assert extract_jsonld(html) == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ====================================================================== salary


class TestSalaryShapes:
    """The value.value nesting is the reason this source is interesting."""

    def test_nested_quantitative_value_is_read(self) -> None:
        """Careers24's real shape, and the one the first parser missed.

        A band-only parser reads ``value["minValue"]`` -> None and
        ``value["maxValue"]`` -> None, and returns a clean (None, None) with no
        error anywhere. Against the live board that meant 0 of 40 salaries
        recorded where 15 exist.
        """
        lo, hi, period, currency, unit, shape = _extract_salary(
            {
                "baseSalary": {
                    "currency": "ZAR",
                    "value": {"@type": "QuantitativeValue", "value": "650000", "unitText": "YEAR"},
                }
            }
        )
        assert (lo, hi) == (650000.0, 650000.0)
        assert shape == "quantitative"
        assert period == "yearly"
        assert currency == "ZAR"
        assert unit == "YEAR"

    def test_nested_value_with_a_daily_rate(self) -> None:
        """Measured verbatim from advert 2393721."""
        lo, _, period, _, _, _ = _extract_salary(
            {
                "baseSalary": {
                    "currency": "ZAR",
                    "value": {"@type": "QuantitativeValue", "value": "180", "unitText": "DAY"},
                }
            }
        )
        assert lo == 180.0
        assert period == "daily"

    def test_empty_unittext_is_not_treated_as_known(self) -> None:
        """Measured on advert 2393720: ``"value": "80", "unitText": ""``.

        Uppercasing the blank into a truthy-looking ``""`` would let it reach
        the period lookup; here it must read as *unknown*, which is what makes
        the cleaner drop the amount rather than call R 80 a yearly salary.
        """
        lo, _, period, _, unit, _ = _extract_salary(
            {
                "baseSalary": {
                    "currency": "ZAR",
                    "value": {"@type": "QuantitativeValue", "value": "80", "unitText": ""},
                }
            }
        )
        assert lo == 80.0
        assert unit is None
        assert period is None

    def test_bare_scalar_shape_is_still_accepted(self) -> None:
        """Defensive: the site has also been seen to emit ``value`` directly."""
        lo, hi, period, _, _, shape = _extract_salary(
            {"baseSalary": {"currency": "ZAR", "value": "650000", "unitText": "YEAR"}}
        )
        assert (lo, hi) == (650000.0, 650000.0)
        assert shape == "single"
        assert period == "yearly"

    def test_range_shape_still_works(self) -> None:
        """Wellfound's and Built In's shape, in case the site ever emits it."""
        lo, hi, period, _, _, shape = _extract_salary(
            {
                "baseSalary": {
                    "currency": "USD",
                    "value": {"minValue": 100000, "maxValue": 120000, "unitText": "YEAR"},
                }
            }
        )
        assert (lo, hi) == (100000.0, 120000.0)
        assert shape == "range"
        assert period == "yearly"

    def test_range_shape_reads_unit_text_from_either_level(self) -> None:
        """Wellfound/Built In put it inside ``value``; some emitters put it outside."""
        outer = _extract_salary(
            {
                "baseSalary": {
                    "currency": "USD",
                    "unitText": "YEAR",
                    "value": {"minValue": 1, "maxValue": 2},
                }
            }
        )
        inner = _extract_salary(
            {
                "baseSalary": {
                    "currency": "USD",
                    "value": {"minValue": 1, "maxValue": 2, "unitText": "YEAR"},
                }
            }
        )
        assert outer[2] == inner[2] == "yearly"

    def test_absent_salary_reports_its_shape(self) -> None:
        assert _extract_salary({})[-1] == "absent"
        assert _extract_salary({"baseSalary": None})[-1] == "absent"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("650000", 650000.0),  # the shape the site uses
            ("R 1 250 000,00", 1250000.0),  # rand with European decimals
            ("$120,000", 120000.0),  # English thousands separator
            ("1.250.000", 1250000.0),  # European thousands separator
            ("ZAR 98 500", 98500.0),
            ("", None),
            (None, None),
            ("n/a", None),  # decoration but no digits
            (True, None),  # a bool is not a salary
        ],
    )
    def test_formatted_monetary_strings_are_coerced(self, raw, expected) -> None:
        """The obvious strip-and-float leaves the spaces in and raises instead."""
        assert (
            _extract_salary({"baseSalary": {"value": {"value": raw, "unitText": "YEAR"}}})[0]
            == expected
        )

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
    def test_every_unit_maps_into_the_schema_vocabulary(self, unit: str, expected: str) -> None:
        _, _, period, _, _, _ = _extract_salary({"baseSalary": {"value": "100", "unitText": unit}})
        assert period == expected
        assert period in ALLOWED_PERIODS

    def test_an_unknown_unit_maps_to_none_not_to_itself(self) -> None:
        """Passing 'FORTNIGHTLY' through would violate the pay_period check."""
        assert _extract_salary({"baseSalary": {"value": "1", "unitText": "FORTNIGHTLY"}})[2] is None


# ==================================================================== location


class TestLocation:
    def test_bare_place_is_read(self) -> None:
        label, country, city, region = _extract_location({"jobLocation": POSTING["jobLocation"]})
        assert (country, city, region) == ("South Africa", "Pretoria", "Gauteng")
        assert label == "Pretoria, Gauteng"

    def test_a_list_of_places_takes_the_first(self) -> None:
        label, country, _, _ = _extract_location(
            {"jobLocation": [POSTING["jobLocation"], {"@type": "Place"}]}
        )
        assert country == "South Africa"

    def test_country_only_still_yields_a_label(self) -> None:
        """A posting with no locality is a real location statement, not nothing."""
        label, country, city, region = _extract_location(
            {"jobLocation": {"address": {"addressCountry": "South Africa"}}}
        )
        assert label == "South Africa"
        assert (country, city, region) == ("South Africa", None, None)

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None)

    def test_province_only_does_not_produce_a_duplicated_label(self) -> None:
        """A posting with no locality puts the province in addressLocality.

        Measured on the first 40 postings, every province-only advert produced
        the label "Gauteng, Gauteng" before this was fixed. Each name is
        emitted once; the city and region fields still both carry the province,
        because that is what the source actually said.
        """
        label, country, city, region = _extract_location(
            {
                "jobLocation": {
                    "address": {
                        "addressLocality": "Gauteng",
                        "addressRegion": "Gauteng",
                        "addressCountry": "South Africa",
                    }
                }
            }
        )
        assert label == "Gauteng"
        assert (country, city, region) == ("South Africa", "Gauteng", "Gauteng")


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = Careers24Parser().parse(
            "2393648",
            detail_html(),
            url="https://www.careers24.com/jobs/adverts/2393648-x",
            listing_page=1,
        )
        assert job.source_job_id == "2393648"
        assert job.title == "Office Administrator"
        assert job.company_name == "Pretoria Office Solutions"
        assert job.country == "South Africa"
        assert job.city == "Pretoria"
        assert job.region == "Gauteng"
        assert job.posted_date == date(2026, 10, 14)
        assert job.closing_date == date(2026, 11, 12)
        assert job.salary_min == job.salary_max == 650000.0
        assert job.salary_period == "yearly"
        assert job.currency_iso_code == "ZAR"
        assert job.employment_type == "FULL_TIME"
        assert job.industry == "Admin"
        # The shape is kept so a markup change is visible in the data.
        assert job.raw["salary_shape"] == "quantitative"

    def test_id_comes_from_the_url_when_jsonld_declares_another(self) -> None:
        """The URL id is authoritative: it is what makes re-runs idempotent."""
        job = Careers24Parser().parse("111", detail_html())
        assert job.source_job_id == "111"

    def test_no_title_raises_rather_than_storing_a_blank_row(self) -> None:
        with pytest.raises(Careers24ParseError, match="no title"):
            Careers24Parser().parse("123", detail_html({}))

    def test_missing_org_falls_back_rather_than_crashing(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "hiringOrganization"}
        assert Careers24Parser().parse("1", detail_html(payload)).company_name == "Unknown employer"

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [
            {"job_id": "1", "html": detail_html()},
            {"job_id": "2", "html": detail_html({})},
            {"job_id": "3", "html": detail_html()},
        ]
        jobs, issues = Careers24Parser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1", "3"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw) -> RawCareers24Job:
        base = Careers24Parser().parse("1", detail_html())
        return base.model_copy(update=kw)

    def test_cleaned_job_matches_the_shared_contract(self) -> None:
        cleaned = Careers24Cleaner().clean_job(self._job())
        assert cleaned.job_title == "Office Administrator"
        assert cleaned.company_name == "Pretoria Office Solutions"
        assert cleaned.location_cleaned == "Pretoria, Gauteng"
        assert cleaned.salary_min == cleaned.salary_max == 650000
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "ZAR"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.posting_date is not None
        assert cleaned.closing_date is not None
        assert "<p>" not in (cleaned.description_clean or "")

    def test_pay_period_is_always_inside_the_schema_vocabulary(self) -> None:
        """A bad value here aborts the shared transaction and fails every later row."""
        for unit in ("YEAR", "MONTH", "HOUR", "FORTNIGHTLY", ""):
            job = self._job(salary_period=None)
            job.raw = {"unit_text": unit}
            assert Careers24Cleaner().clean_job(job).pay_period in ALLOWED_PERIODS

    def test_salary_disclosed_is_false_without_a_salary(self) -> None:
        cleaned = Careers24Cleaner().clean_job(self._job(salary_min=None, salary_max=None))
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None

    def test_amount_without_a_period_is_dropped_not_defaulted_to_yearly(self) -> None:
        """R 80 with unitText '' is a rate, not an annual salary.

        Storing it as yearly would put a figure wrong by three orders of
        magnitude into the corpus. The amount is kept in the payload so the
        information is not lost, and the row is marked undisclosed.
        """
        cleaned = Careers24Cleaner().clean_job(
            self._job(salary_min=80.0, salary_max=80.0, salary_period=None)
        )
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_amount_without_period"] == 80.0

    def test_amount_with_a_known_period_is_kept(self) -> None:
        cleaned = Careers24Cleaner().clean_job(
            self._job(salary_min=180.0, salary_max=180.0, salary_period="daily")
        )
        assert cleaned.salary_min == 180
        assert cleaned.salary_disclosed is True
        assert cleaned.pay_period == "daily"

    def test_reversed_bounds_are_ordered(self) -> None:
        cleaned = Careers24Cleaner().clean_job(self._job(salary_min=120000, salary_max=100000))
        assert (cleaned.salary_min, cleaned.salary_max) == (100000, 120000)

    def test_company_whitespace_is_collapsed(self) -> None:
        cleaned = Careers24Cleaner().clean_job(self._job(company_name="Acme   Corp\n Ltd"))
        assert cleaned.company_name == "Acme Corp Ltd"

    def test_country_only_location_is_kept(self) -> None:
        job = self._job(location=None, country="South Africa", city=None, region=None)
        assert Careers24Cleaner().clean_job(job).location_cleaned == "South Africa"

    def test_salary_shape_is_carried_into_the_payload(self) -> None:
        cleaned = Careers24Cleaner().clean_job(self._job())
        assert cleaned.raw_payload["salary_shape"] == "quantitative"

    def test_clean_jobs_logs_and_survives_a_bad_record(self) -> None:
        class Exploding(RawCareers24Job):
            def __getattribute__(self, item: str):  # noqa: ANN204
                if item == "title":
                    raise RuntimeError("boom")
                return super().__getattribute__(item)

        good = self._job()
        bad = self._job(source_job_id="2")
        object.__setattr__(bad, "__class__", Exploding)
        cleaned = Careers24Cleaner().clean_jobs([good, bad])
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
    def test_schema_vocabulary_maps_to_the_database_codes(self, raw: str, expected: str) -> None:
        assert _map_employment_type(raw) == expected

    def test_unknown_value_is_none_and_stays_in_the_payload(self) -> None:
        assert _map_employment_type("SOMETHING_NEW") is None
        assert _map_employment_type("") is None
        assert _map_employment_type(None) is None

    def test_first_listed_form_wins(self) -> None:
        assert _map_employment_type("PART_TIME,FULL_TIME") == "part_time"


# ==================================================================== validator


class TestValidator:
    def test_a_full_batch_passes(self) -> None:
        from job_market_intel.validation.careers24_validator import Careers24BatchValidator

        parser = Careers24Parser()
        raw = [{"job_id": str(i), "html": detail_html()} for i in range(12)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        report = Careers24BatchValidator().validate(raw, parsed)
        assert report.passed

    def test_salary_absence_is_counted_but_not_fatal(self) -> None:
        """6 of 8 measured postings had none. That must not fail a batch."""
        from job_market_intel.validation.careers24_validator import Careers24BatchValidator

        payload = {k: v for k, v in POSTING.items() if k != "baseSalary"}
        parser = Careers24Parser()
        raw = [{"job_id": str(i), "html": detail_html(payload)} for i in range(12)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        report = Careers24BatchValidator().validate(raw, parsed)
        assert report.passed
        assert "salary" in str(getattr(report, "missing_fields", {}) or report).lower()


# ==================================================================== settings


class TestSettings:
    def test_env_prefix_is_careers24(self) -> None:
        assert Careers24Settings().base_url == "https://www.careers24.com"

    def test_overrides_are_honoured(self) -> None:
        s = Careers24Settings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Careers24Settings(max_pages=0)
        with pytest.raises(ValidationError):
            Careers24Settings(inter_request_delay_seconds=-1.0)

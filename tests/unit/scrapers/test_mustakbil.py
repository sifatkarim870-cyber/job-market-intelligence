"""Unit tests for the Mustakbil scraper.

Each test pins a fact measured on the live site on 2026-10-16, which is how
every other scraper's tests here are written. The ones that would each have
broken the source if guessed:

  1. **There is no working pagination.** ``/jobs?page=2`` is byte-identical to
     page 1 -- 398,957 bytes, the same 43 ids. A scraper built the obvious way
     fetches one page and reports success. Breadth comes from category paths,
     and only 8 of 25 plausible slugs exist.
  2. **``baseSalary`` nests the band under ``value.value``** -- the same shape
     Apna uses and different from Wellfound's and Built In's. A parser written
     for either of those reads ``None`` for both bounds here, silently, because
     salary is an optional field.
  3. ``validThrough`` carries **seven** fractional-second digits
     (``2027-01-16T19:00:00.0000000Z``), which ``datetime.fromisoformat``
     rejects before Python 3.11. A date parser that trusts the standard
     library returns no closing date for every posting.
  4. ``experienceRequirements`` is a nested
     ``{"@type": "OccupationalExperienceRequirements", "monthsOfExperience": 12}``
     object, not the bare string other boards emit.
  5. ``identifier.value`` is a **string** here, where Apna's is a JSON number.
  6. The site throttles **at the connection level**, not with a 429: a listing
     burst succeeds and then every detail fetch fails with ``ConnectionError``.

Run with:  uv run pytest tests/unit/scrapers/test_mustakbil.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.mustakbil_cleaner import (
    MustakbilCleaner,
    _map_employment_type,
    _safe_pay_period,
)
from job_market_intel.scrapers.mustakbil.client import _JOB_LINK, MustakbilClient
from job_market_intel.scrapers.mustakbil.config import MustakbilSettings
from job_market_intel.scrapers.mustakbil.exceptions import (
    MustakbilParseError,
    MustakbilResponseError,
)
from job_market_intel.scrapers.mustakbil.parser import (
    MustakbilParser,
    _extract_experience,
    _extract_location,
    _extract_salary,
    _parse_date,
    extract_jsonld,
)

#: The schema's own vocabulary.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}

#: Trimmed verbatim from a live detail page fetched 2026-10-16
#: (/jobs/job/1436508). Note validThrough's 7-digit fraction and the band
#: nested under value.value.
POSTING = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "AI & Digital Marketing S Instructors",
    "description": (
        "<b>Job Description</b>: Sharp Visions is looking for a talented "
        "professional.<br><br><b>Responsibilities:</b><ul><li>Teach AI tools."
        "</li></ul>"
    ),
    "identifier": {
        "@type": "PropertyValue",
        "name": "Sharp Visions IT Company",
        "value": "1436508",
    },
    "datePosted": "2026-10-16T07:40:53+00:00",
    "validThrough": "2027-01-16T19:00:00.0000000Z",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Sharp Visions IT Company",
        "logo": "https://s.mustakbil.com/employers/7e841f64f10d48cb931e41f7a0d61c3d.jpg",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Rawalpindi",
            "addressCountry": "PK",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "PKR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 40000,
            "maxValue": 60000,
            "unitText": "MONTH",
        },
    },
    "experienceRequirements": {
        "@type": "OccupationalExperienceRequirements",
        "monthsOfExperience": 12,
    },
    "directApply": False,
    "url": "https://www.mustakbil.com/jobs/job/1436508",
}


def detail_html(posting: dict | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_link_regex_takes_the_numeric_id(self) -> None:
        found = {
            m.group(2): m.group(1)
            for m in _JOB_LINK.finditer('<a href="/jobs/job/1436508">Instructor</a>')
        }
        assert found == {"1436508": "/jobs/job/1436508"}

    def test_link_regex_ignores_category_and_nav_links(self) -> None:
        html = (
            '<a href="/jobs/pakistan/sales">Sales</a>'
            '<a href="/account/login">Login</a>'
            '<a href="/jobs/job/12">x</a>'  # too short an id
        )
        assert list(_JOB_LINK.finditer(html)) == []

    def test_no_page_parameter_is_sent(self) -> None:
        """/jobs?page=2 is byte-identical to page 1, so it must never be sent."""
        client = MustakbilClient(MustakbilSettings())
        assert client.listing_url("/jobs") == "https://mustakbil.com/jobs"
        assert "page" not in client.listing_url("/jobs")

    def test_all_nine_configured_paths_are_distinct(self) -> None:
        paths = MustakbilSettings().listing_paths
        assert len(paths) == 9
        assert len(set(paths)) == 9
        assert paths[0] == "/jobs"
        assert all(p.startswith("/jobs") for p in paths)

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = MustakbilClient(MustakbilSettings(max_jobs_per_run=5))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(MustakbilResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_repeated_path_is_not_counted_twice(self) -> None:
        """First listing wins, so a posting reachable from two paths is fetched once."""
        body = '<a href="/jobs/job/1436508">a</a><a href="/jobs/job/1436509">b</a>'
        client = MustakbilClient(
            MustakbilSettings(
                listing_paths=["/jobs", "/jobs/pakistan/sales"],
                inter_request_delay_seconds=0.0,
            )
        )
        client._fetch = lambda url: body  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert set(found) == {"1436508", "1436509"}

    def test_discovery_walks_every_path_even_with_a_small_fetch_budget(self) -> None:
        """Regression: the fetch budget must not cut discovery short.

        An earlier version broke out of the discovery loop once
        ``max_jobs_per_run`` was reached. Since ``/jobs`` alone yields 43 ids,
        ``--max-jobs 40`` stopped after the first path and the eight category
        paths -- the only source of breadth here, because ``?page=`` is ignored
        -- were never requested. The budget governs detail fetching, not
        discovery.
        """
        requested: list[str] = []

        def fake_fetch(url: str) -> str:
            requested.append(url)
            # A distinct id per path, so the union is 3 rather than 1.
            return f'<a href="/jobs/job/{1436500 + len(requested)}">x</a>'

        client = MustakbilClient(
            MustakbilSettings(
                listing_paths=["/jobs", "/jobs/pakistan/sales", "/jobs/pakistan/engineering"],
                max_jobs_per_run=1,  # smaller than one page's yield
                inter_request_delay_seconds=0.0,
            )
        )
        client._fetch = fake_fetch  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()

        assert failures == {}
        assert len(requested) == 3, "discovery stopped early; category paths were skipped"
        assert len(found) == 3, "each path contributed its own posting"

    def test_fetch_budget_caps_detail_fetches_not_discovery(self) -> None:
        """max_jobs_per_run must limit the records returned, not the walk."""
        body = "".join(f'<a href="/jobs/job/{1436500 + i}">x</a>' for i in range(10))
        client = MustakbilClient(
            MustakbilSettings(
                listing_paths=["/jobs", "/jobs/pakistan/sales"],
                max_jobs_per_run=3,
                fetch_description=False,
                inter_request_delay_seconds=0.0,
            )
        )
        client._fetch = lambda url: body  # type: ignore[method-assign]
        records, _ = client.fetch_raw_jobs()
        assert len(records) == 3
        assert len({r["job_id"] for r in records}) == 3


# ====================================================================== JSON-LD


class TestJsonLdExtraction:
    def test_top_level_posting_is_found(self) -> None:
        assert extract_jsonld(detail_html())["title"].startswith("AI & Digital")

    def test_malformed_json_is_skipped_not_fatal(self) -> None:
        assert extract_jsonld("<html><script type='application/ld+json'>{oops</script>") == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ====================================================================== dates


class TestDates:
    def test_seven_digit_fraction_is_handled(self) -> None:
        """The real validThrough. fromisoformat rejects this before Python 3.11."""
        assert _parse_date("2027-01-16T19:00:00.0000000Z") == date(2027, 1, 16)

    @pytest.mark.parametrize(
        "raw",
        [
            "2026-10-16T07:40:53+00:00",
            "2026-10-16",
            "2026-10-16T00:00:00.000Z",
            "2026-10-16 07:40:53",
            "2026-10-16T07:40:53.123456789+05:00",
        ],
    )
    def test_common_timestamp_shapes(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 10, 16)

    @pytest.mark.parametrize("raw", ["", None, "not a date", "16/10/2026"])
    def test_junk_is_none_not_an_exception(self, raw) -> None:
        assert _parse_date(raw) is None


# ====================================================================== salary


class TestSalaryShapes:
    def test_band_nested_under_value_value_is_read(self) -> None:
        lo, hi, period, currency, unit, shape = _extract_salary(POSTING)
        assert (lo, hi) == (40000.0, 60000.0)
        assert period == "monthly"
        assert currency == "PKR"
        assert unit == "MONTH"
        assert shape == "band"

    def test_the_wellfound_shape_still_works(self) -> None:
        lo, hi, _, _, _, shape = _extract_salary(
            {
                "baseSalary": {
                    "currency": "USD",
                    "value": {"minValue": 100000, "maxValue": 120000, "unitText": "YEAR"},
                }
            }
        )
        assert (lo, hi) == (100000.0, 120000.0)
        assert shape == "band"

    def test_the_careers24_scalar_shape_still_works(self) -> None:
        lo, hi, _, _, _, shape = _extract_salary(
            {"baseSalary": {"currency": "ZAR", "value": {"value": "650000", "unitText": "YEAR"}}}
        )
        assert (lo, hi) == (650000.0, 650000.0)
        assert shape == "quantitative"

    def test_absent_salary_reports_its_shape(self) -> None:
        assert _extract_salary({})[-1] == "absent"

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

    def test_empty_unittext_is_not_treated_as_known(self) -> None:
        """Present but blank, which uppercasing would turn into a truthy-looking ''."""
        _, _, period, _, unit, _ = _extract_salary(
            {"baseSalary": {"value": {"value": "80", "unitText": ""}}}
        )
        assert unit is None
        assert period is None


# ==================================================================== location


class TestLocation:
    def test_country_is_the_iso_code(self) -> None:
        label, country, city = _extract_location({"jobLocation": POSTING["jobLocation"]})
        assert (country, city) == ("PK", "Rawalpindi")
        assert label == "Rawalpindi"

    def test_country_only_still_yields_a_label(self) -> None:
        label, country, city = _extract_location(
            {"jobLocation": {"address": {"addressCountry": "PK"}}}
        )
        assert label == "PK"
        assert (country, city) == ("PK", None)

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None)


class TestExperience:
    def test_nested_occupational_requirements(self) -> None:
        """The measured shape. A string-typed field would read nothing here."""
        months, raw = _extract_experience(
            {"experienceRequirements": POSTING["experienceRequirements"]}
        )
        assert months == 12
        assert raw is None  # nothing left after dropping @type and the figure

    def test_extra_keys_are_preserved_as_text(self) -> None:
        months, raw = _extract_experience(
            {
                "experienceRequirements": {
                    "@type": "OccupationalExperienceRequirements",
                    "monthsOfExperience": 6,
                    "description": "Some text",
                }
            }
        )
        assert months == 6
        assert "Some text" in raw

    def test_a_bare_string_is_accepted(self) -> None:
        months, raw = _extract_experience({"experienceRequirements": "3 years"})
        assert months is None
        assert raw == "3 years"

    def test_absent_is_none(self) -> None:
        assert _extract_experience({}) == (None, None)


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = MustakbilParser().parse("1436508", detail_html(), listing_path="/jobs")
        assert job.source_job_id == "1436508"
        assert job.title.startswith("AI & Digital")
        assert job.company_name == "Sharp Visions IT Company"
        assert job.company_logo_url is not None
        assert (job.country, job.city) == ("PK", "Rawalpindi")
        assert (job.salary_min, job.salary_max) == (40000.0, 60000.0)
        assert job.salary_period == "monthly"
        assert job.currency_iso_code == "PKR"
        assert job.posted_date == date(2026, 10, 16)
        assert job.closing_date == date(2027, 1, 16)
        assert job.months_of_experience == 12
        assert job.employment_type == "FULL_TIME"
        assert job.direct_apply is False
        assert job.raw["salary_shape"] == "band"
        assert job.raw["identifier_value_type"] == "str"

    def test_url_comes_from_jsonld_when_none_is_passed(self) -> None:
        assert MustakbilParser().parse("1", detail_html()).url == POSTING["url"]

    def test_no_title_raises(self) -> None:
        with pytest.raises(MustakbilParseError, match="no title"):
            MustakbilParser().parse("1", detail_html({}))

    def test_missing_org_falls_back(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "hiringOrganization"}
        assert MustakbilParser().parse("1", detail_html(payload)).company_name == "Unknown employer"

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [{"job_id": "1", "html": detail_html()}, {"job_id": "2", "html": detail_html({})}]
        jobs, issues = MustakbilParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return MustakbilParser().parse("1436508", detail_html()).model_copy(update=kw)

    def test_cleaned_job_matches_the_shared_contract(self) -> None:
        cleaned = MustakbilCleaner().clean_job(self._job())
        assert cleaned.job_title.startswith("AI & Digital")
        assert cleaned.company_name == "Sharp Visions IT Company"
        assert cleaned.location_cleaned == "Rawalpindi"
        assert (cleaned.salary_min, cleaned.salary_max) == (40000, 60000)
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "PKR"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.closing_date is not None

    def test_html_is_stripped_from_the_description(self) -> None:
        """Every measured Mustakbil description carries <b>/<ul>/<li>."""
        body = MustakbilCleaner().clean_job(self._job()).description_clean
        assert body and "<b>" not in body and "<li>" not in body

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        """Honest empty, not a parser miss. Nothing is counted for it in the census."""
        assert MustakbilCleaner().clean_job(self._job()).skills == []

    def test_reversed_bounds_are_ordered(self) -> None:
        cleaned = MustakbilCleaner().clean_job(self._job(salary_min=60000, salary_max=40000))
        assert (cleaned.salary_min, cleaned.salary_max) == (40000, 60000)

    def test_company_whitespace_is_collapsed(self) -> None:
        cleaned = MustakbilCleaner().clean_job(self._job(company_name="Sharp   Visions\n IT"))
        assert cleaned.company_name == "Sharp Visions IT"

    def test_extras_reach_the_payload(self) -> None:
        job = MustakbilParser().parse("1436508", detail_html(), listing_path="/jobs/pakistan/sales")
        payload = MustakbilCleaner().clean_job(job).raw_payload
        assert payload["months_of_experience"] == 12
        assert payload["salary_shape"] == "band"
        assert payload["listing_path"] == "/jobs/pakistan/sales"


class TestPayPeriodGuard:
    @pytest.mark.parametrize("value", ["MONTH", "YEAR", "FORTNIGHTLY", "monthly", None, ""])
    def test_never_escapes_the_schema_vocabulary(self, value) -> None:
        """ck_job_salaries_pay_period does not reject one row -- it aborts the
        transaction, which fails every remaining row in the batch."""
        assert _safe_pay_period(value) in ALLOWED_PERIODS

    def test_a_valid_value_passes_through(self) -> None:
        assert _safe_pay_period("daily") == "daily"

    def test_fallback_is_monthly_not_yearly(self) -> None:
        """Every measured Mustakbil salary was MONTH; yearly would be wrong."""
        assert _safe_pay_period("NONSENSE") == "monthly"


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
        assert _map_employment_type("NEW_THING") is None
        assert _map_employment_type(None) is None


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 25, posting: dict | None = None):
        from job_market_intel.validation.mustakbil_validator import (
            MustakbilBatchValidator,
        )

        parser = MustakbilParser()
        raw = [{"job_id": str(1436500 + i), "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return MustakbilBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_absent_salary_is_counted_not_fatal(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "baseSalary"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("salary") == 1.0

    def test_absent_experience_is_counted_not_fatal(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "experienceRequirements"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("experience") == 1.0

    def test_present_fields_are_not_counted_missing(self) -> None:
        rates = self._report().missing_field_rates
        for field in ("salary", "experience", "description", "closing_date"):
            assert rates.get(field, 0.0) == 0.0

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_the_delay_is_the_measured_one(self) -> None:
        """3.5s was measured as too fast; this must not silently drop below it."""
        assert MustakbilSettings().inter_request_delay_seconds >= 3.5

    def test_defaults(self) -> None:
        s = MustakbilSettings()
        assert s.base_url == "https://mustakbil.com"
        assert s.max_jobs_per_run == 120

    def test_overrides_are_honoured(self) -> None:
        s = MustakbilSettings(max_jobs_per_run=30)
        assert s.max_jobs_per_run == 30

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MustakbilSettings(inter_request_delay_seconds=-1.0)
        with pytest.raises(ValidationError):
            MustakbilSettings(max_jobs_per_run=0)

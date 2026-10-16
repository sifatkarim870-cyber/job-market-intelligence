"""Unit tests for the CareerJunction scraper.

Each test pins a fact measured on the live site on 2026-10-17, which is how every
other scraper's tests here is written. The ones that would each have broken the
source if guessed:

  1. **The JSON-LD is malformed.** The ``description`` string contains raw
     newlines and HTML entities, which makes ``json.loads`` raise ``Invalid
     control character``. A strict parser reads nothing at all from every page
     -- which is exactly what the first probe reported, before the fix was
     found. The fix is ``json.loads(block, strict=False)``.
  2. **There is no ``identifier``** (0 of 1 postings), so the URL id is the
     only stable key the board offers. A parser that expects one stores nothing
     identifiable and re-runs insert duplicates forever.
  3. **There is no real ``baseSalary``** (0 of 1). CareerJunction publishes
     ``"R Undisclosed"``, which is not a salary, so ``salary_disclosed`` is
     always ``False`` and no ``pay_period`` is claimed about a figure that does
     not exist.
  4. ``datePosted`` / ``validThrough`` are formatted ``"2026/10/16 10:33:33 AM"``
     -- not ISO 8601. A date parser that trusts the standard library returns no
     dates for every posting.
  5. Descriptions run **3400+** characters, so the 100-character gate used
     everywhere else here is comfortable.

Run with:  uv run pytest tests/unit/scrapers/test_careerjunction.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.careerjunction_cleaner import (
    CareerJunctionCleaner,
    _map_employment_type,
)
from job_market_intel.scrapers.careerjunction.client import _JOB_LINK, CareerJunctionClient
from job_market_intel.scrapers.careerjunction.config import CareerJunctionSettings
from job_market_intel.scrapers.careerjunction.exceptions import (
    CareerJunctionParseError,
    CareerJunctionResponseError,
)
from job_market_intel.scrapers.careerjunction.parser import (
    CareerJunctionParser,
    _extract_location,
    _parse_date,
    extract_jsonld,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-17
#: (/executive-personal-assistant-job-2646292.aspx). The description contains raw
#: newlines and HTML entities, which is the trap.
POSTING = {
    "@context": "http://schema.org",
    "@type": "JobPosting",
    "title": "Executive Personal Assistant",
    "url": "https://www.careerjunction.co.za/executive-personal-assistant-job-2646292.aspx",
    "datePosted": "2026/10/16 10:33:33 AM",
    "validThrough": "2026/11/14 9:33:32 AM",
    "description": (
        "&lt;span&gt;&lt;p&gt;Leading pharmaceutical manufacturer requires an "
        "experienced Executive Personal Assistant to join t"
    ),
    "industry": "admin, office & support",
    "employmentType": "Default",
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "ZAR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": "R Undisclosed",
            "maxValue": "R Undisclosed",
        },
    },
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Ultra Personnel cc",
        "url": "https://www.careerjunction.co.za//companies/28524/ultra-personnel-cc",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Centurion",
            "addressCountry": "ZA",
        },
        "geo": {"@type": "GeoCoordinates", "latitude": -25.85, "longitude": 28.19},
    },
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
        html = '<a href="/executive-personal-assistant-job-2646292.aspx">x</a>'
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        assert found == {"2646292": "/executive-personal-assistant-job-2646292.aspx"}

    def test_link_regex_ignores_non_job_paths(self) -> None:
        html = (
            '<a href="/jobs">All jobs</a>'
            '<a href="/companies/28524/ultra-personnel-cc">Company</a>'
            '<a href="/executive-personal-assistant-job-1234.aspx">x</a>'  # id too short (4 digits)
        )
        assert list(_JOB_LINK.finditer(html)) == []

    def test_listing_url_omits_the_query_on_page_one(self) -> None:
        client = CareerJunctionClient(CareerJunctionSettings())
        assert client.listing_url(1) == "https://www.careerjunction.co.za/jobs"
        assert client.listing_url(2) == "https://www.careerjunction.co.za/jobs?page=2"

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = CareerJunctionClient(CareerJunctionSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(CareerJunctionResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_repeated_page_is_not_counted_twice(self) -> None:
        """First listing wins, so a posting reachable from two pages is fetched once."""
        body = (
            '<a href="/executive-personal-assistant-job-2646292.aspx">a</a>'
            '<a href="/office-manager-job-2646308.aspx">b</a>'
        )
        client = CareerJunctionClient(
            CareerJunctionSettings(
                max_pages=2,
                inter_request_delay_seconds=0.0,
            )
        )
        client._fetch = lambda url: body  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert set(found) == {"2646292", "2646308"}


# ====================================================================== JSON-LD


class TestMalformedJsonLd:
    """The description contains raw newlines and HTML entities. This is the trap."""

    def test_strict_parsing_fails_on_the_real_payload(self) -> None:
        """A strict parser reads nothing at all from every page.

        The site's raw block has literal newlines inside the description
        string. ``json.dumps`` of a Python dict would escape them, so this
        builds the malformed text the way the site actually emits it.
        """
        raw = '{"@type": "JobPosting", "title": "x", "description": "line1\nline2"}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)

    def test_lenient_parsing_succeeds(self) -> None:
        assert extract_jsonld(detail_html())["title"] == "Executive Personal Assistant"

    def test_the_description_survives_with_its_entities(self) -> None:
        """The entities are content, not structure -- they must not be lost."""
        desc = extract_jsonld(detail_html())["description"]
        assert "&lt;span&gt;" in desc
        assert "pharmaceutical" in desc

    def test_malformed_json_is_skipped_not_fatal(self) -> None:
        assert extract_jsonld("<html><script type='application/ld+json'>{oops</script>") == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ======================================================================= dates


class TestDates:
    @pytest.mark.parametrize(
        "raw", ["2026/10/16 10:33:33 AM", "2026/10/16", "2026/10/16T10:33:33Z"]
    )
    def test_careerjunction_format(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 10, 16)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_junk_is_none_not_an_exception(self, raw) -> None:
        assert _parse_date(raw) is None


# ==================================================================== location


class TestLocation:
    def test_country_is_the_iso_code(self) -> None:
        label, country, city, lat, lon = _extract_location({"jobLocation": POSTING["jobLocation"]})
        assert country == "ZA"
        assert city == "Centurion"
        assert label == "Centurion"
        assert (lat, lon) == (-25.85, 28.19)

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None, None)


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = CareerJunctionParser().parse(
            "2646292",
            detail_html(),
            url="https://www.careerjunction.co.za/executive-personal-assistant-job-2646292.aspx",
        )
        assert job.source_job_id == "2646292"
        assert job.title == "Executive Personal Assistant"
        assert job.company_name == "Ultra Personnel cc"
        assert job.company_url is not None
        assert (job.country, job.city) == ("ZA", "Centurion")
        assert (job.latitude, job.longitude) == (-25.85, 28.19)
        assert job.posted_date == date(2026, 10, 16)
        assert job.closing_date == date(2026, 11, 14)
        assert job.employment_type == "Default"
        assert job.industry == "admin, office & support"

    def test_the_url_id_is_the_key_because_there_is_no_identifier(self) -> None:
        """0 of 1 measured postings carry one."""
        job = CareerJunctionParser().parse("2646292", detail_html())
        assert job.source_job_id == "2646292"
        assert job.raw["has_identifier"] is False

    def test_absent_base_salary_is_recorded_not_silently_ignored(self) -> None:
        job = CareerJunctionParser().parse("2646292", detail_html())
        assert job.raw["has_base_salary"] is True  # the field exists but is "R Undisclosed"

    def test_no_title_raises(self) -> None:
        with pytest.raises(CareerJunctionParseError, match="no title"):
            CareerJunctionParser().parse("1", detail_html({}))

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [{"job_id": "1", "html": detail_html()}, {"job_id": "2", "html": detail_html({})}]
        jobs, issues = CareerJunctionParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return CareerJunctionParser().parse("2646292", detail_html()).model_copy(update=kw)

    def test_no_salary_is_ever_claimed(self) -> None:
        """CareerJunction publishes 'R Undisclosed'. Asserting a period about a
        figure that does not exist is a small lie a later analysis cannot see."""
        cleaned = CareerJunctionCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_country_only_location_is_kept(self) -> None:
        job = self._job(location=None, country="ZA", city=None)
        assert CareerJunctionCleaner().clean_job(job).location_cleaned == "ZA"

    def test_html_entities_are_unescaped_and_markup_stripped(self) -> None:
        body = CareerJunctionCleaner().clean_job(self._job()).description_clean
        assert body and "&lt;" not in body and "<span>" not in body

    def test_language_is_recorded_as_english(self) -> None:
        assert CareerJunctionCleaner().clean_job(self._job()).raw_payload["language"] == "en"

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert CareerJunctionCleaner().clean_job(self._job()).skills == []

    def test_company_whitespace_is_collapsed(self) -> None:
        job = self._job(company_name="Ultra   Personnel\n cc")
        assert CareerJunctionCleaner().clean_job(job).company_name == "Ultra Personnel cc"

    def test_quality_score_ignores_salary_entirely(self) -> None:
        """Every other source's score counts it; including it here would
        depress every row by 1/9 for a fact about the board."""
        cleaned = CareerJunctionCleaner().clean_job(self._job())
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
            ("PERMANENT", "full_time"),
        ],
    )
    def test_schema_vocabulary_maps_to_database_codes(self, raw, expected) -> None:
        assert _map_employment_type(raw) == expected

    def test_careerjunction_default_maps_to_none(self) -> None:
        """'Default' is not a schema.org employmentType value."""
        assert _map_employment_type("Default") is None

    def test_unknown_is_none(self) -> None:
        assert _map_employment_type("NEW") is None
        assert _map_employment_type(None) is None


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 25, posting: dict | None = None):
        from job_market_intel.validation.careerjunction_validator import (
            CareerJunctionBatchValidator,
        )

        parser = CareerJunctionParser()
        raw = [{"job_id": str(2646200 + i), "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return CareerJunctionBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_a_very_short_description_counts_as_missing(self) -> None:
        """The floor must still catch a real extraction failure.

        Note this shows up in the field census, not in ``passed``:
        ``validate_batch`` only fails on record counts, skip rate and duplicate
        ids. The census is where a per-field regression becomes visible.
        """
        report = self._report(posting={**POSTING, "description": ""})
        assert report.missing_field_rates.get("description") == 1.0

    def test_absent_location_is_counted_but_not_fatal(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "jobLocation"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("location") == 1.0

    def test_no_salary_is_ever_reported_missing(self) -> None:
        """A salary check here would be a permanent 100% failure saying nothing."""
        rates = self._report().missing_field_rates
        assert "salary" not in rates

    def test_a_thin_batch_does_fail(self) -> None:
        """23 of 25 is healthy (2 expired pages); 3 is a broken feed."""
        assert self._report(n=23).passed
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = CareerJunctionSettings()
        assert s.base_url == "https://www.careerjunction.co.za"
        assert s.listing_path == "/jobs"
        assert s.max_jobs_per_run == 25

    def test_overrides_are_honoured(self) -> None:
        s = CareerJunctionSettings(max_pages=2, max_jobs_per_run=10)
        assert (s.max_pages, s.max_jobs_per_run) == (2, 10)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CareerJunctionSettings(inter_request_delay_seconds=-1.0)
        with pytest.raises(ValidationError):
            CareerJunctionSettings(max_jobs_per_run=0)

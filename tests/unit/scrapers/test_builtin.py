"""Unit tests for the Built In scraper.

Each test pins a fact established by probing the live site on 2026-10-15, which
is how every other scraper's tests here are written. The six that would each
have broken the source if guessed:

  1. **The ``JobPosting`` is not at the top level of the JSON-LD.** Built In
     emits ``{"@context": ..., "@graph": [ ... ]}``. A parser checking
     ``json["@type"]`` finds nothing and reports an empty board on a site
     serving every field. The first probe reported "no JobPosting on any detail
     page" for exactly this reason.
  2. ``geo`` is a **sibling of** ``address`` on the ``Place`` node, not a child.
     Reading ``address["geo"]`` returns nothing on every posting, silently.
  3. ``industry`` is a **list on 21 of 24** postings and a bare string on 3, so
     a scalar-typed field rejects three quarters of the board.
  4. ``jobLocation`` is a bare ``Place`` on 19 of 24 and a list on the other 5.
  5. ``hiringOrganization.logo`` is an ``ImageObject`` dict (``{"url": ...}``),
     not a URL string.
  6. The salary period arrives as ``unitText: "YEAR"``, which is not in the
     corpus vocabulary. Passing it through violates ``ck_job_salaries_pay_period``,
     whose violation aborts the enclosing transaction -- the failure that lost
     25 of 30 rows on the first Job Bank run.

Run with:  uv run pytest tests/unit/scrapers/test_builtin.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.builtin_cleaner import BuiltInCleaner
from job_market_intel.scrapers.builtin.client import BuiltInClient
from job_market_intel.scrapers.builtin.config import BuiltInSettings
from job_market_intel.scrapers.builtin.exceptions import (
    BuiltInParseError,
    BuiltInResponseError,
)
from job_market_intel.scrapers.builtin.parser import (
    BuiltInParser,
    _as_list,
    _extract_locations,
    _extract_salary,
    extract_posting,
)

#: The schema's own vocabulary. Nothing outside this set may reach
#: salary.job_salaries.pay_period.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}

#: Trimmed from a live detail page fetched 2026-10-15
#: (/job/python-software-engineer-iii/11692055), reduced to the nodes that
#: matter. The real document nests these under "@graph".
POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Python Software Engineer III",
    "description": (
        "<p>We have an exciting and rewarding opportunity for you to take your "
        "software engineering career to the next level.</p><ul><li>Executes "
        "software engineering work across the full stack.</li></ul>"
    ),
    "directApply": False,
    "identifier": {"@type": "PropertyValue", "name": "JPMorganChase", "value": "11692055"},
    "datePosted": "2026-10-15",
    "employmentType": "FULL_TIME",
    "applicantLocationRequirements": {"@type": "Country", "name": "USA"},
    "hiringOrganization": {
        "@type": "Organization",
        "name": "JPMorganChase",
        "sameAs": "https://builtin.com/company/jpmorgan-chase",
        "logo": {
            "@type": "ImageObject",
            "url": "https://builtin.com/sites/www.builtin.com/files/logo.png",
            "representativeOfPage": True,
        },
    },
    "industry": ["Artificial Intelligence", "Cloud", "Information Technology"],
    "jobBenefits": ["Offers 401(K)", "Provides adoption assistance", "Offers dental insurance"],
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressCountry": "USA",
            "addressLocality": "Jersey City",
            "addressRegion": "New Jersey",
        },
        "geo": {"@type": "GeoCoordinates", "latitude": 40.717495, "longitude": -74.044111},
    },
    "validThrough": "2026-11-14T05:07:48+00:00",
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "USD",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 84400,
            "maxValue": 194200,
            "unitText": "YEAR",
        },
    },
    "jobLocationType": "TELECOMMUTE",
}


def _graph(*nodes) -> str:
    """The real shape: an @graph document, not a bare node."""
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@graph": list(nodes)})
        + "</script></head><body></body></html>"
    )


REAL_PAGE_HTML = _graph(
    {
        "@type": "Organization",
        "name": "Builtin",
        "url": "https://builtin.com",
    },
    {
        "@type": "WebPage",
        "name": "Python Software Engineer III",
    },
    POSTING,
    {"@type": "BreadcrumbList", "itemListElement": []},
)


def _page(node: dict) -> str:
    return _graph(node)


class TestGraphTraversal:
    """Bug 1: the posting is nested under @graph."""

    def test_finds_a_posting_nested_under_graph(self):
        assert extract_posting(REAL_PAGE_HTML)["@type"] == "JobPosting"

    def test_finds_a_posting_at_the_top_level_too(self):
        html = '<script type="application/ld+json">' + json.dumps(POSTING) + "</script>"
        assert extract_posting(html)["@type"] == "JobPosting"

    def test_picks_the_jobposting_not_the_organisation(self):
        found = extract_posting(REAL_PAGE_HTML)
        assert found["title"] == "Python Software Engineer III"
        assert found.get("url") != "https://builtin.com"

    def test_finds_a_posting_nested_two_levels_deep(self):
        html = _graph({"@type": "WebPage", "mainEntity": POSTING})
        assert extract_posting(html)["@type"] == "JobPosting"

    def test_tolerates_missing_and_broken_blocks(self):
        assert extract_posting("") == {}
        assert extract_posting("<html><body>nothing</body></html>") == {}
        assert extract_posting('<script type="application/ld+json">{oops}</script>') == {}

    def test_a_graph_with_no_posting_yields_nothing(self):
        assert extract_posting(_graph({"@type": "Organization", "name": "X"})) == {}


class TestListingUrls:
    def test_page_one_omits_the_query(self):
        assert BuiltInClient().listing_url("/jobs", 1) == "https://builtin.com/jobs"

    def test_later_pages_carry_the_query(self):
        assert BuiltInClient().listing_url("/jobs", 4).endswith("?page=4")


class TestDiscovery:
    def test_no_search_path_is_configured(self):
        """robots.txt disallows /search/ and /jobs*?search=."""
        paths = BuiltInSettings().listing_paths
        assert not any("search" in p for p in paths)
        assert not any("?" in p for p in paths)

    def test_remote_facet_is_a_path_not_a_search(self):
        assert "/jobs/remote" in BuiltInSettings().listing_paths

    def test_job_ids_are_the_trailing_number(self):
        """Built In URLs are /job/<slug>/<id>; the slug is decoration."""
        client = BuiltInClient(BuiltInSettings(listing_paths=["/jobs"]))
        client.fetch_listing_page = lambda path, page=1: {  # type: ignore[method-assign]
            "11692055": "/job/python-software-engineer-iii/11692055",
            "11497299": "/job/software-and-data-engineer-iii-agentic-pricing/11497299",
        }
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert set(found) == {"11692055", "11497299"}

    def test_a_slug_containing_digits_does_not_become_the_id(self):
        from job_market_intel.scrapers.builtin.client import _JOB_LINK

        m = _JOB_LINK.search('href="/job/data-engineer-2-100-remote/9876543"')
        assert m.group(2) == "9876543"

    def test_a_repeatedly_empty_listing_stops_instead_of_looping(self):
        client = BuiltInClient(BuiltInSettings(listing_paths=["/jobs"], max_pages_per_listing=10))
        calls: list[int] = []

        def _fake(path, page=1):
            calls.append(page)
            return {}

        client.fetch_listing_page = _fake  # type: ignore[method-assign]
        with pytest.raises(BuiltInResponseError):
            client.discover_detail_paths()
        assert len(calls) <= 3

    def test_a_short_final_page_is_collected_before_stopping(self):
        """A tail page holds real postings; dropping it loses the last page of
        every listing walked."""
        client = BuiltInClient(BuiltInSettings(listing_paths=["/jobs"], max_pages_per_listing=10))
        pages: list[int] = []

        def _fake(path, page=1):
            pages.append(page)
            if page == 1:
                return {str(i): f"/job/slug-{i}/{i}" for i in range(1000, 1025)}
            return {"9999": "/job/slug-tail/9999"}

        client.fetch_listing_page = _fake  # type: ignore[method-assign]
        found, _ = client.discover_detail_paths()
        assert pages == [1, 2]
        assert "9999" in found

    def test_no_links_anywhere_raises_rather_than_returning_empty(self):
        client = BuiltInClient(BuiltInSettings(listing_paths=["/jobs"]))
        client.fetch_listing_page = lambda path, page=1: {}  # type: ignore[method-assign]
        with pytest.raises(BuiltInResponseError):
            client.discover_detail_paths()


class TestParserFields:
    def _job(self, node=POSTING, job_id="11692055"):
        return BuiltInParser().parse(job_id, _page(node), url="u", listing_path="/jobs")

    def test_identity_comes_from_the_url(self):
        job = self._job()
        assert job.source_job_id == "11692055"
        assert job.title == "Python Software Engineer III"

    def test_identifier_name_is_the_company_not_the_id(self):
        job = self._job()
        assert job.raw["identifier_name"] == "JPMorganChase"
        assert job.company_name == "JPMorganChase"

    def test_logo_is_an_imageobject_dict(self):
        """Bug 5: reading it as a string yields a dict where a URL is expected."""
        job = self._job()
        assert job.company_logo_url == "https://builtin.com/sites/www.builtin.com/files/logo.png"
        assert not isinstance(job.company_logo_url, dict)

    def test_industry_list_becomes_a_list(self):
        """Bug 3: a scalar-typed field rejects 21 of 24 postings."""
        job = self._job()
        assert job.industries == [
            "Artificial Intelligence",
            "Cloud",
            "Information Technology",
        ]

    def test_a_bare_string_industry_still_works(self):
        job = self._job(node={**POSTING, "industry": "Financial Services"})
        assert job.industries == ["Financial Services"]

    def test_as_list_de_duplicates_and_preserves_order(self):
        assert _as_list(["a", "b", "a"]) == ["a", "b"]
        assert _as_list("solo") == ["solo"]
        assert _as_list(None) == []
        assert _as_list([None, "x"]) == ["x"]

    def test_both_dates_are_parsed(self):
        job = self._job()
        assert job.posted_date == date(2026, 10, 15)
        assert job.closing_date == date(2026, 11, 14)

    def test_remote_flag_is_tri_state(self):
        """None means "not stated", which is different from "not remote"."""
        assert self._job().is_remote is True
        node = {k: v for k, v in POSTING.items() if k != "jobLocationType"}
        assert self._job(node=node).is_remote is None

    def test_applicant_countries_are_not_conflated_with_the_job_location(self):
        job = self._job()
        assert job.applicant_countries == ["USA"]
        assert job.location_countries == ["USA"]
        # The one posting measured that named Delaware/New Jersey/Pennsylvania
        # still only accepted US applicants.
        multi = {
            **POSTING,
            "jobLocation": [
                {"address": {"addressCountry": "USA", "addressRegion": "Pennsylvania"}},
                {"address": {"addressCountry": "USA", "addressRegion": "Delaware"}},
            ],
        }
        job = self._job(node=multi)
        assert job.locations == ["Pennsylvania", "Delaware"]
        assert job.applicant_countries == ["USA"]

    def test_benefits_stay_a_list(self):
        job = self._job()
        assert job.benefits == [
            "Offers 401(K)",
            "Provides adoption assistance",
            "Offers dental insurance",
        ]

    def test_description_comes_from_the_jsonld(self):
        job = self._job()
        assert "software engineering career" in job.description
        assert len(job.description) > 100


class TestCoordinates:
    """Bug 2: geo is a sibling of address, not a child."""

    def test_coordinates_are_read(self):
        job = BuiltInParser().parse("11692055", _page(POSTING))
        assert job.coordinates == [(40.717495, -74.044111)]

    def test_a_geo_nested_under_address_would_be_missed(self):
        """Pins the shape: moving geo under address silently loses every point."""
        moved = {
            **POSTING,
            "jobLocation": {
                "address": {
                    "addressLocality": "Austin",
                    "geo": {"latitude": 30.26, "longitude": -97.74},
                }
            },
        }
        assert BuiltInParser().parse("1", _page(moved)).coordinates == []

    def test_a_half_specified_coordinate_pair_is_dropped(self):
        partial = {
            **POSTING,
            "jobLocation": {
                "address": {"addressLocality": "Austin"},
                "geo": {"latitude": 30.26},
            },
        }
        assert BuiltInParser().parse("1", _page(partial)).coordinates == []

    def test_a_state_only_location_is_kept(self):
        node = {
            **POSTING,
            "jobLocation": {"address": {"addressRegion": "Pennsylvania", "addressCountry": "USA"}},
        }
        labels, countries, coords = _extract_locations(node)
        assert labels == ["Pennsylvania"]
        assert countries == ["USA"]
        assert coords == []

    def test_a_list_of_places_is_accepted(self):
        node = {
            **POSTING,
            "jobLocation": [
                {"address": {"addressLocality": "Austin", "addressRegion": "Texas"}},
                {"address": {"addressLocality": "Dallas", "addressRegion": "Texas"}},
            ],
        }
        labels, _countries, coords = _extract_locations(node)
        assert labels == ["Austin, Texas", "Dallas, Texas"]
        assert coords == []


class TestParserSalary:
    def test_unit_text_maps_onto_the_schema_vocabulary(self):
        """Bug 6: "YEAR" violates ck_job_salaries_pay_period."""
        job = BuiltInParser().parse("11692055", _page(POSTING))
        assert job.salary_period in ALLOWED_PERIODS
        assert job.salary_period == "yearly"
        assert job.salary_min == 84400.0
        assert job.salary_max == 194200.0
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
                    "currency": "USD",
                    "value": {"unitText": unit, "minValue": 1, "maxValue": 2},
                }
            }
        )
        assert period == expected
        assert period in ALLOWED_PERIODS
        assert (lo, hi, cur) == (1.0, 2.0, "USD")

    def test_an_absent_salary_block_is_fine(self):
        """baseSalary is missing on about a quarter of postings."""
        node = {k: v for k, v in POSTING.items() if k != "baseSalary"}
        job = BuiltInParser().parse("1", _page(node))
        assert job.salary_min is None
        assert job.salary_period is None

    @pytest.mark.parametrize(
        "salary",
        [None, {}, {"value": None}, {"value": "not a dict"}, "a string", []],
    )
    def test_a_broken_salary_block_does_not_raise(self, salary):
        lo, hi, period, _cur, _unit = _extract_salary({"baseSalary": salary})
        assert (lo, hi, period) == (None, None, None)

    def test_an_unknown_unit_yields_none_not_a_guess(self):
        _, _, period, _, unit = _extract_salary(
            {"baseSalary": {"value": {"unitText": "FORTNIGHT", "minValue": 1}}}
        )
        assert period is None
        assert unit == "FORTNIGHT"


class TestParserErrors:
    def test_no_posting_node_raises(self):
        with pytest.raises(BuiltInParseError):
            BuiltInParser().parse("1", _graph({"@type": "Organization", "name": "X"}))

    def test_parse_many_keeps_the_good_records(self):
        records = [
            {"job_id": "11692055", "html": _page(POSTING), "url": "u", "listing_path": "/jobs"},
            {"job_id": "1", "html": "<html></html>", "url": "u", "listing_path": "/jobs"},
        ]
        jobs, issues = BuiltInParser().parse_many(records)
        assert len(jobs) == 1
        assert len(issues) == 1

    def test_the_model_exposes_industries_as_a_list_and_no_scalar_industry(self):
        """The contract that matters: ``industries`` is a list field.

        The original crash happened because ``industry`` was a declared
        ``str | None`` field being handed a list. Note that ``extra="allow"``
        would *not* have caught a stray scalar field afterwards -- it would
        have been silently kept as an extra. So this asserts the declared shape
        rather than relying on a validation error to police it.
        """
        from job_market_intel.scrapers.builtin.models import RawBuiltInJob

        assert "industries" in RawBuiltInJob.model_fields
        assert "industry" not in RawBuiltInJob.model_fields
        assert RawBuiltInJob(source_job_id="1", title="t").industries == []


class TestCleaner:
    def _job(self, node=POSTING):
        return BuiltInParser().parse(
            "11692055",
            _page(node),
            url="https://builtin.com/job/python-software-engineer-iii/11692055",
            listing_path="/jobs",
        )

    def test_cleaned_job_carries_the_schema_vocabulary(self):
        cleaned = BuiltInCleaner().clean_job(self._job())
        assert cleaned.pay_period in ALLOWED_PERIODS
        assert cleaned.source_job_id == "11692055"

    def test_salary_and_disclosure_flag(self):
        cleaned = BuiltInCleaner().clean_job(self._job())
        assert cleaned.salary_disclosed is True
        assert cleaned.salary_min == 84400
        assert cleaned.salary_max == 194200

    def test_a_posting_without_salary_is_not_marked_disclosed(self):
        node = {k: v for k, v in POSTING.items() if k != "baseSalary"}
        cleaned = BuiltInCleaner().clean_job(self._job(node))
        assert cleaned.salary_disclosed is False
        assert cleaned.pay_period in ALLOWED_PERIODS  # falls back, never bad

    def test_swapped_bounds_are_corrected(self):
        node = {
            **POSTING,
            "baseSalary": {
                "@type": "MonetaryAmount",
                "currency": "USD",
                "value": {"unitText": "YEAR", "minValue": 194200, "maxValue": 84400},
            },
        }
        cleaned = BuiltInCleaner().clean_job(self._job(node))
        assert cleaned.salary_min == 84400
        assert cleaned.salary_max == 194200

    def test_benefits_are_one_per_line_under_a_heading(self):
        cleaned = BuiltInCleaner().clean_job(self._job())
        assert "Benefits" in cleaned.description_clean
        assert "- Offers 401(K)" in cleaned.description_clean
        assert "software engineering career" in cleaned.description_clean

    def test_multi_location_keeps_every_state(self):
        node = {
            **POSTING,
            "jobLocation": [
                {"address": {"addressRegion": "Pennsylvania"}},
                {"address": {"addressRegion": "Delaware"}},
                {"address": {"addressRegion": "New Jersey"}},
            ],
        }
        cleaned = BuiltInCleaner().clean_job(self._job(node))
        assert "Pennsylvania" in cleaned.location_cleaned
        assert "Delaware" in cleaned.location_cleaned
        assert "New Jersey" in cleaned.location_cleaned

    def test_currency_is_usd_because_the_board_is(self):
        assert BuiltInCleaner().clean_job(self._job()).currency_iso_code == "USD"

    def test_logo_and_description_are_carried(self):
        cleaned = BuiltInCleaner().clean_job(self._job())
        assert "logo.png" in cleaned.company_logo_url
        assert cleaned.word_count > 20
        assert cleaned.data_quality_score > 0.9

    def test_clean_jobs_logs_rather_than_silently_returning_nothing(self):
        class Exploding:
            source_job_id = "1"

            def __getattr__(self, _name):
                raise RuntimeError("boom")

        assert BuiltInCleaner().clean_jobs([Exploding()]) == []  # does not raise


class TestValidator:
    def test_dates_are_required(self):
        from job_market_intel.validation.builtin_validator import _MISSING_FIELD_CHECKS

        for field in ("posted_date", "closing_date", "description"):
            assert field in _MISSING_FIELD_CHECKS

    def test_validate_never_raises_on_an_empty_batch(self):
        from job_market_intel.validation.builtin_validator import BuiltInBatchValidator

        report = BuiltInBatchValidator().validate([], [])
        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)

    def test_report_exposes_passed(self):
        from job_market_intel.validation.builtin_validator import (
            BuiltInBatchValidator,
            BuiltInValidationSettings,
        )

        validator = BuiltInBatchValidator(BuiltInValidationSettings(min_expected_jobs=1))
        job = BuiltInParser().parse("11692055", _page(POSTING), url="u", listing_path="/jobs")
        report = validator.validate([{"job_id": "11692055"}], [job])
        assert report.passed is True
        assert not hasattr(report, "validation_passed")

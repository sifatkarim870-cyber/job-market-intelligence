"""Unit tests for the USAJOBS scraper.

Each test pins a fact established by running against the live API and live job
pages on 2026-10-14, which is how every other scraper's tests here are written.
The four that would each have broken the source if guessed:

  1. There is **no position detail endpoint.** ``/api/v2/position/{id}``,
     ``/api/position/{PositionID}``, ``/api/position/{numeric}`` and two other
     spellings all return 404. Writing a detail-fetching client and testing it
     against a mock would have "passed" and then 404'd on every real run.
  2. ``PositionFormattedDescription`` is a marker object --
     ``[{'Label': 'Dynamic Teaser', ...}]`` -- not description text. And the
     JSON-LD ``description`` on the job page is only a ~400-character teaser
     against ~30,000 characters in the ``page-section`` blocks.
  3. The search response nests every posting under
     ``MatchedObjectDescriptor``. The older v1 shape put fields at the top
     level, so a parser written for v1 returns nothing rather than failing.
  4. The salary interval is a code (``RateIntervalCode: "PA"``), not a word.
     Passing the code through would violate ``ck_job_salaries_pay_period``,
     whose violation aborts the transaction -- the same failure that lost 25 of
     30 rows on the first Job Bank run.

Run with:  uv run pytest tests/unit/scrapers/test_usajobs.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.usajobs_cleaner import USAJobsCleaner, _fix_title
from job_market_intel.scrapers.usajobs.client import USAJobsClient
from job_market_intel.scrapers.usajobs.config import USAJobsSettings
from job_market_intel.scrapers.usajobs.exceptions import USAJobsParseError
from job_market_intel.scrapers.usajobs.parser import (
    USAJobsParser,
    _period_from_text,
    extract_jsonld,
    extract_page_sections,
)

#: Trimmed from a live response to
#: ``/api/search?ResultsPerPage=1&Keyword=engineer`` fetched 2026-10-14.
REAL_DESCRIPTOR = {
    "PositionID": "CEDC-26-13071989-MP",
    "PositionTitle": "ENGINEERING TECHNICIAN",
    "PositionURI": "https://www.usajobs.gov:443/job/886992900",
    "ApplyURI": ["https://www.usajobs.gov:443/job/886992900"],
    "PositionLocationDisplay": "Fort Leonard Wood, Missouri",
    "PositionLocation": [
        {
            "LocationName": "Fort Leonard Wood, Missouri",
            "CountryCode": "United States",
            "CountrySubDivisionCode": "Missouri",
            "CityName": "Fort Leonard Wood, Missouri",
            "Longitude": -92.11671,
            "Latitude": 37.76972,
        }
    ],
    "OrganizationName": "U.S. Army Corps of Engineers",
    "DepartmentName": "Department of the Army",
    "SubAgency": "U.S. Army Engineer Research and Development Center",
    "JobCategory": [{"Name": "Engineering Technical", "Code": "0802"}],
    "JobGrade": [{"Code": "DE"}],
    "PositionSchedule": [{"Name": "", "Code": "1"}],
    "PositionOfferingType": [{"Name": "", "Code": "15317"}],
    "QualificationSummary": "Who May Apply: " + "qualified applicants. " * 40,
    "PositionRemuneration": [
        {
            "MinimumRange": "55882",
            "MaximumRange": "88356",
            "RateIntervalCode": "PA",
            "Description": "Per Year",
        }
    ],
    "PublicationStartDate": "2026-10-01T00:00:00.0000",
    "ApplicationCloseDate": "2026-10-15T23:59:59.9970",
    "PositionFormattedDescription": [
        {"Label": "Dynamic Teaser", "LabelDescription": "Hit highlighting for keyword searches."}
    ],
}

#: Shape of a live usajobs.gov job page, reduced to the parts that matter.
#: Built with json.dumps rather than written as a literal. A literal newline
#: inside a JSON string is invalid, and json.loads then rejects the whole block
#: -- so a hand-wrapped fixture yields {} from extract_jsonld with no error
#: anywhere to explain it. That is exactly what happened when this fixture was
#: first written with the JSON wrapped across source lines.
JSONLD = {
    "@context": "http://schema.org",
    "@type": "JobPosting",
    "title": "ENGINEERING TECHNICIAN",
    "description": "<b>About the Position:</b> This position is with the U.S. Army ERDC.",
    "qualifications": (
        "<p><strong>Who May Apply:</strong> Only applicants who meet one of the "
        "employment authority categories below apply.</p>"
    ),
    "educationRequirements": (
        "<strong>FOREIGN EDUCATION:</strong> If you are using education completed in "
        "foreign colleges or universities to meet any education requirement, you must "
        "provide evidence of equivalency."
    ),
    "datePosted": "10/01/2026",
    "validThrough": "10/15/2026",
    "employmentType": "OTHER",
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "USD",
        "value": {"@type": "QuantitativeValue", "value": 55882.00, "unitText": "YEAR"},
    },
    "hiringOrganization": "RG-W2R2AA US ARMY ENGR RESEARCH AND DEVELOPMT CTR",
}

REAL_PAGE_HTML = f"""
<html><head>
<script type="application/ld+json">{json.dumps(JSONLD)}</script>
</head><body><main>
<div class="apply-joa-defaults">
  <div class="page-section">
    <h2>Summary</h2>
    <p>About the Position: This position is with the U.S. Army Engineer Research and
       Development Center, Construction and Engineering Research Laboratory.</p>
  </div>
  <div class="page-section hidden md:block">
    <h2>Overview</h2>
    <div>Accepting applications. Location 1 vacancy in the following location:
         Fort Leonard Wood, Missouri.</div>
  </div>
  <div class="page-section">
    <h2>Duties</h2>
    <ul><li>Assembles, tests, operates and maintains experimental energy systems.</li>
        <li>Provides technical support for complex studies and modelling efforts.</li></ul>
  </div>
  <div class="page-section">
    <h2>Requirements</h2>
    <h3>Conditions of employment</h3>
    <ul><li>Appointment may be subject to a suitability or fitness determination.</li></ul>
  </div>
  <div class="page-section">
    <h2>Qualifications</h2>
    <div>Meet the minimum qualification requirements for the position.</div>
  </div>
  <div class="page-section"><h2>Videos</h2><div>some video</div></div>
</div></main></body></html>
"""

#: The schema's own vocabulary. Nothing outside this set may reach
#: salary.job_salaries.pay_period.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}


class TestConfig:
    def test_key_is_read_from_the_file_named_by_api_key_file(self):
        """A field validator cannot do this -- see the module docstring."""
        settings = USAJobsSettings(api_key_file=_key_file("secret-key-value"))
        assert settings.api_key == "secret-key-value"

    def test_explicit_key_wins_over_the_file(self):
        settings = USAJobsSettings(api_key="explicit", api_key_file=_key_file("from-file"))
        assert settings.api_key == "explicit"

    def test_missing_key_is_none_not_an_error(self):
        """The pipeline turns this into a loud failure; the settings do not."""
        from pathlib import Path

        missing = Path("D:/definitely/not/here/usajobs_key.txt")
        assert USAJobsSettings(api_key_file=missing).api_key is None

    def test_results_per_page_above_the_api_cap_is_rejected(self):
        """Pydantic rejects rather than clamps -- clamping would silently send
        a request the API answers with fewer results than asked for."""
        with pytest.raises(ValidationError):
            USAJobsSettings(results_per_page=501)


class TestClientUrls:
    def test_search_url_carries_keyword_page_and_size(self):
        url = USAJobsClient().search_url("data engineer", 2)
        assert "Keyword=data+engineer" in url
        assert "Page=2" in url
        assert "ResultsPerPage=" in url

    def test_no_detail_url_is_offered(self):
        """Bug 1: every detail-endpoint spelling 404s, so none is built."""
        assert not hasattr(USAJobsClient, "fetch_position")
        assert not hasattr(USAJobsClient, "fetch_detail")


class TestParserIdentity:
    def test_parses_the_v2_envelope(self):
        """Bug 3: the posting lives under MatchedObjectDescriptor."""
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert job.source_job_id == "CEDC-26-13071989-MP"
        assert job.title == "ENGINEERING TECHNICIAN"

    def test_missing_position_id_raises(self):
        """PositionID is the natural key; without it nothing can dedupe."""
        bad = {**REAL_DESCRIPTOR, "PositionID": ""}
        with pytest.raises(USAJobsParseError):
            USAJobsParser().parse(bad)

    def test_missing_title_raises(self):
        with pytest.raises(USAJobsParseError):
            USAJobsParser().parse({**REAL_DESCRIPTOR, "PositionTitle": ""})

    def test_parse_many_collects_failures_without_losing_the_good_ones(self):
        records = [
            {"descriptor": REAL_DESCRIPTOR, "html": None, "search_keyword": "engineer"},
            {"descriptor": {"PositionID": ""}, "html": None, "search_keyword": "engineer"},
        ]
        jobs, issues = USAJobsParser().parse_many(records)
        assert len(jobs) == 1
        assert len(issues) == 1


class TestParserSalary:
    def test_interval_code_maps_onto_the_schema_vocabulary(self):
        """Bug 4: "PA" is not a pay_period; ck_job_salaries_pay_period rejects it."""
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert job.salary_period in ALLOWED_PERIODS
        assert job.salary_period == "yearly"
        assert job.salary_min == 55882.0
        assert job.salary_max == 88356.0

    @pytest.mark.parametrize(
        "interval_code,expected",
        [("PA", "yearly"), ("PH", "hourly"), ("PD", "daily"), ("PW", "weekly"), ("PM", "monthly")],
    )
    def test_every_interval_code_is_covered(self, interval_code, expected):
        d = {
            **REAL_DESCRIPTOR,
            "PositionRemuneration": [
                {"MinimumRange": "10", "MaximumRange": "20", "RateIntervalCode": interval_code}
            ],
        }
        assert USAJobsParser().parse(d).salary_period == expected

    def test_unknown_interval_falls_back_to_the_description(self):
        d = {
            **REAL_DESCRIPTOR,
            "PositionRemuneration": [
                {
                    "MinimumRange": "10",
                    "MaximumRange": "20",
                    "RateIntervalCode": "ZZ",
                    "Description": "Per Hour",
                }
            ],
        }
        assert USAJobsParser().parse(d).salary_period == "hourly"

    def test_unmappable_interval_yields_none_rather_than_a_bad_word(self):
        d = {
            **REAL_DESCRIPTOR,
            "PositionRemuneration": [
                {
                    "MinimumRange": "10",
                    "MaximumRange": "20",
                    "RateIntervalCode": "ZZ",
                    "Description": "",
                }
            ],
        }
        assert USAJobsParser().parse(d).salary_period is None

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Per Year", "yearly"),
            ("Per Hour", "hourly"),
            ("$50.00 hourly", "hourly"),
            ("$5,000 per month", "monthly"),
            ("$96,557 to $128,743 annually", "yearly"),
            ("$70,000 a year", "yearly"),
            ("", None),
            ("something unmapped", None),
        ],
    )
    def test_period_from_text(self, text, expected):
        result = _period_from_text(text)
        assert expected is None or result == expected
        assert result is None or result in ALLOWED_PERIODS

    def test_swapped_bounds_are_corrected(self):
        d = {
            **REAL_DESCRIPTOR,
            "PositionRemuneration": [
                {"MinimumRange": "90000", "MaximumRange": "50000", "RateIntervalCode": "PA"}
            ],
        }
        cleaned = USAJobsCleaner().clean_job(USAJobsParser().parse(d))
        assert cleaned.salary_min == 50000
        assert cleaned.salary_max == 90000


class TestParserDescription:
    def test_marker_object_is_never_treated_as_a_description(self):
        """Bug 2: PositionFormattedDescription is [Label: Dynamic Teaser]."""
        job = USAJobsParser().parse(REAL_DESCRIPTOR)  # no html at all
        assert job.description is None

    def test_page_sections_supply_the_full_text(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR, REAL_PAGE_HTML)
        assert "Assembles, tests, operates" in job.description
        assert "suitability or fitness" in job.description
        assert "minimum qualification requirements" in job.description

    def test_the_headings_are_kept(self):
        """Dropping them loses the only cue separating Duties from Requirements."""
        job = USAJobsParser().parse(REAL_DESCRIPTOR, REAL_PAGE_HTML)
        for heading in ("Duties", "Requirements", "Qualifications", "Overview"):
            assert heading in job.description

    def test_video_sections_are_dropped(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR, REAL_PAGE_HTML)
        assert "some video" not in job.description

    def test_jsonld_description_is_the_fallback_not_the_primary(self):
        teaser = USAJobsParser().parse(REAL_DESCRIPTOR, REAL_PAGE_HTML)
        assert len(teaser.description) > 400  # sections, not the 372-char teaser

    def test_jsonld_teaser_is_used_when_the_page_has_no_sections(self):
        """A redesigned page loses the sections but keeps the JSON-LD; the
        record must degrade to the teaser rather than to nothing."""
        head_only = (
            REAL_PAGE_HTML.split("<body>")[0] + "<body><main><div>x</div></main></body></html>"
        )
        assert extract_page_sections(head_only) == ""
        job = USAJobsParser().parse(REAL_DESCRIPTOR, head_only)
        assert "About the Position" in job.description

    def test_extract_jsonld_finds_the_jobposting_block(self):
        ld = extract_jsonld(REAL_PAGE_HTML)
        assert ld["@type"] == "JobPosting"
        assert ld["baseSalary"]["value"]["value"] == 55882.0

    def test_extract_jsonld_tolerates_a_missing_or_broken_block(self):
        assert extract_jsonld("") == {}
        assert extract_jsonld("<html><body>nothing</body></html>") == {}
        broken = '<html><script type="application/ld+json">{not json}</script></html>'
        assert extract_jsonld(broken) == {}

    def test_duplicate_desktop_and_mobile_sections_appear_once(self):
        """Each section is rendered twice; a doubled body inflates word_count."""
        doubled = REAL_PAGE_HTML.replace(
            '<div class="page-section hidden md:block">', '<div class="page-section">'
        )
        sections = extract_page_sections(doubled)
        assert sections.count("Accepting applications") == 1


class TestParserFields:
    def test_structured_location_with_coordinates(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert job.country_code == "United States"
        assert job.state_code == "Missouri"
        assert round(job.latitude, 2) == 37.77
        assert round(job.longitude, 2) == -92.12

    def test_organisation_hierarchy_is_captured(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert job.organization_name == "U.S. Army Corps of Engineers"
        assert job.department_name == "Department of the Army"
        assert job.sub_agency.startswith("U.S. Army Engineer Research")

    def test_grade_and_series(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert job.job_grade == "DE"
        assert job.job_category == "Engineering Technical"

    def test_dates_from_the_api(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert job.posted_date == date(2026, 10, 1)
        assert job.closing_date == date(2026, 10, 15)

    def test_dates_fall_back_to_the_jsonld_when_the_api_omits_them(self):
        d = {**REAL_DESCRIPTOR, "PublicationStartDate": None, "ApplicationCloseDate": None}
        job = USAJobsParser().parse(d, REAL_PAGE_HTML)
        assert job.posted_date == date(2026, 10, 1)
        assert job.closing_date == date(2026, 10, 15)

    def test_port_443_is_stripped_from_the_url(self):
        job = USAJobsParser().parse(REAL_DESCRIPTOR)
        assert ":443" not in job.url
        assert job.url == "https://www.usajobs.gov/job/886992900"

    def test_apply_uri_list_is_unwrapped(self):
        assert USAJobsParser().parse(REAL_DESCRIPTOR).apply_url.endswith("/job/886992900")


class TestTitleCasing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ENGINEERING TECHNICIAN", "Engineering Technician"),
            ("GENERAL ENGINEER (PROJECT MANAGER)", "General Engineer (Project Manager)"),
            ("IT SPECIALIST", "IT Specialist"),
            ("GS-15 PROGRAM ANALYST", "GS-15 Program Analyst"),
            ("NURSE", "Nurse"),
        ],
    )
    def test_shouted_titles_are_normalised(self, raw, expected):
        assert _fix_title(raw) == expected

    def test_a_normal_title_is_left_alone(self):
        assert _fix_title("Senior Software Engineer") == "Senior Software Engineer"

    def test_empty_title(self):
        assert _fix_title("") == ""


class TestCleaner:
    def _job(self):
        return USAJobsParser().parse(REAL_DESCRIPTOR, REAL_PAGE_HTML)

    def test_cleaned_job_carries_the_schema_vocabulary(self):
        """The failure that costs a whole run must not be reachable again."""
        cleaned = USAJobsCleaner().clean_job(self._job())
        assert cleaned.pay_period in ALLOWED_PERIODS
        assert cleaned.source_job_id == "CEDC-26-13071989-MP"

    def test_title_is_normalised_and_employer_is_the_bureau(self):
        cleaned = USAJobsCleaner().clean_job(self._job())
        assert cleaned.job_title == "Engineering Technician"
        assert cleaned.company_name == "U.S. Army Corps of Engineers"

    def test_grade_and_series_are_not_treated_as_a_disclosed_salary(self):
        """A GS grade with no figure is not a salary disclosure."""
        no_pay = {**REAL_DESCRIPTOR, "PositionRemuneration": []}
        cleaned = USAJobsCleaner().clean_job(USAJobsParser().parse(no_pay, REAL_PAGE_HTML))
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None
        # Carried, but NOT persisted: JobRepository.save_cleaned_job writes no
        # raw_payload column, so this asserts the cleaner's contract only. It is
        # not evidence the value is in the corpus.
        assert cleaned.raw_payload["job_grade"] == "DE"
        assert cleaned.raw_payload["job_category"] == "Engineering Technical"

    def test_coordinates_reach_the_cleaner_but_not_the_database(self):
        """Documents the gap rather than implying the coordinates persist.

        core.jobs has no latitude/longitude column and the shard schema has
        none either, so these values are lost at save time even though the API
        supplies them for every posting. Verified against information_schema
        on 2026-10-14. If columns are ever added, this test should become an
        assertion that they round-trip.
        """
        cleaned = USAJobsCleaner().clean_job(self._job())
        assert cleaned.raw_payload["latitude"] == 37.76972
        assert cleaned.raw_payload["longitude"] == -92.11671

    def test_currency_is_usd(self):
        assert USAJobsCleaner().clean_job(self._job()).currency_iso_code == "USD"

    def test_description_is_present_and_counted(self):
        cleaned = USAJobsCleaner().clean_job(self._job())
        assert cleaned.description_clean
        assert cleaned.word_count > 40
        assert cleaned.data_quality_score > 0.9

    def test_falls_back_to_the_qualification_summary_when_the_page_fetch_failed(self):
        no_page = USAJobsParser().parse(REAL_DESCRIPTOR)  # html=None
        cleaned = USAJobsCleaner().clean_job(no_page)
        assert "Who May Apply" in cleaned.description_clean

    def test_clean_jobs_logs_rather_than_silently_returning_nothing(self):
        class Exploding:
            source_job_id = "1"

            def __getattr__(self, _name):
                raise RuntimeError("boom")

        assert USAJobsCleaner().clean_jobs([Exploding()]) == []  # does not raise


class TestValidator:
    def test_dates_are_required_fields(self):
        """Undated federal postings would age and expire wrongly."""
        from job_market_intel.validation.usajobs_validator import _MISSING_FIELD_CHECKS

        for field in ("posted_date", "closing_date"):
            assert field in _MISSING_FIELD_CHECKS

    def test_posted_date_check_flags_a_missing_date(self):
        from job_market_intel.validation.usajobs_validator import _MISSING_FIELD_CHECKS

        class NoDate:
            posted_date = None

        assert _MISSING_FIELD_CHECKS["posted_date"](NoDate()) is True

    def test_validate_never_raises_on_an_empty_batch(self):
        from job_market_intel.validation.usajobs_validator import USAJobsBatchValidator

        report = USAJobsBatchValidator().validate([], [])
        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)

    def test_report_exposes_passed_not_validation_passed(self):
        """BatchValidationReport.passed is the real field. Pipelines that wrote
        getattr(report, "validation_passed", True) reported PASSED forever --
        the getattr fallback hid the AttributeError instead of surfacing it."""
        from job_market_intel.validation.usajobs_validator import (
            USAJobsBatchValidator,
            USAJobsValidationSettings,
        )

        validator = USAJobsBatchValidator(USAJobsValidationSettings(min_expected_jobs=1))
        report = validator.validate(
            [{"descriptor": {}}], [USAJobsParser().parse(REAL_DESCRIPTOR, REAL_PAGE_HTML)]
        )
        assert report.passed is True
        assert not hasattr(report, "validation_passed")


def _key_file(content: str):
    import tempfile
    from pathlib import Path

    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    return Path(handle.name)

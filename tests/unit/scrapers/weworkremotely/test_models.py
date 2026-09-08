"""Unit tests for job_market_intel.scrapers.weworkremotely.models.RawWWRJob.

This is the meatiest test module for this source, deliberately — unlike
RemoteOK's raw model (mostly straight field aliasing), ``RawWWRJob`` does
real transformation work in its validators (see ``models.py``'s module
docstring for the full list of why), and each one is a genuine,
independently-testable piece of logic:
    - Splitting WWR's combined "Company: Job Title" string.
    - Extracting a slug from the guid/link URL for source_job_id.
    - Splitting the comma-separated skills string.
    - Parsing RFC 822 dates (not RemoteOK's ISO-8601).
    - The complete absence of a salary field (this model has none).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.weworkremotely.models import RawWWRJob


class TestTitleSplitting:
    def test_splits_company_and_job_title_on_first_colon_space(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(title="Customer.io: Mid-Market Account Executive, Americas")
        assert job.company_name == "Customer.io"
        assert job.job_title == "Mid-Market Account Executive, Americas"

    def test_splits_on_first_separator_only_when_multiple_colons_present(
        self, make_raw_wwr_job
    ) -> None:
        # A colon inside the job title itself (after the first "Company: ")
        # must not cause a second, wrong split.
        job = make_raw_wwr_job(title="GitLab: Associate Solutions Architect: EMEA")
        assert job.company_name == "GitLab"
        assert job.job_title == "Associate Solutions Architect: EMEA"

    def test_direct_job_title_and_company_name_bypass_title_splitting(
        self, make_raw_wwr_job
    ) -> None:
        # Test-ergonomics escape hatch: constructing directly with
        # job_title=/company_name= should not require also composing a
        # matching "title" string.
        job = make_raw_wwr_job(job_title="Engineer", company_name="Acme", title=None)
        assert job.job_title == "Engineer"
        assert job.company_name == "Acme"

    def test_missing_separator_raises_validation_error(self, make_raw_wwr_job) -> None:
        with pytest.raises(ValidationError):
            make_raw_wwr_job(title="Just A Title With No Separator")

    def test_none_title_raises_validation_error(self, make_raw_wwr_job) -> None:
        with pytest.raises(ValidationError):
            make_raw_wwr_job(title=None)

    def test_whitespace_around_split_parts_is_stripped(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(title="  Acme Corp  :   Backend Engineer  ")
        assert job.company_name == "Acme Corp"
        assert job.job_title == "Backend Engineer"


class TestSourceJobIdExtraction:
    def test_extracts_trailing_slug_from_guid_url(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(
            guid="https://weworkremotely.com/remote-jobs/acme-corp-backend-engineer"
        )
        assert job.source_job_id == "acme-corp-backend-engineer"

    def test_strips_trailing_slash_before_extracting_slug(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(guid="https://weworkremotely.com/remote-jobs/acme-corp-engineer/")
        assert job.source_job_id == "acme-corp-engineer"

    def test_plain_value_with_no_slash_passes_through_unchanged(self, make_raw_wwr_job) -> None:
        # Supports direct construction (e.g. in other fixtures/tests)
        # without a full URL — the validator only extracts FROM a
        # URL shape, it never invents one. Note: when both the alias
        # (guid) and the field name (source_job_id) are supplied
        # together, Pydantic resolves via the alias, so this test
        # exercises the pass-through path through guid itself, which is
        # also the realistic path (a raw-shaped dict only ever has "guid",
        # never "source_job_id").
        job = make_raw_wwr_job(guid="123")
        assert job.source_job_id == "123"

    def test_empty_guid_raises_validation_error(self, make_raw_wwr_job) -> None:
        with pytest.raises(ValidationError):
            make_raw_wwr_job(guid="")

    def test_none_guid_raises_validation_error(self, make_raw_wwr_job) -> None:
        with pytest.raises(ValidationError):
            make_raw_wwr_job(guid=None)


class TestSkillsParsing:
    def test_splits_comma_separated_skills_string(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(skills="Python, Django, AWS")
        assert job.skills == ["Python", "Django", "AWS"]

    def test_empty_skills_string_yields_empty_list(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(skills="")
        assert job.skills == []

    def test_none_skills_yields_empty_list(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(skills=None)
        assert job.skills == []

    def test_extra_whitespace_and_empty_entries_are_dropped(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(skills="Python,, Django ,  , AWS  ")
        assert job.skills == ["Python", "Django", "AWS"]

    def test_list_input_is_passed_through_as_strings(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(skills=["Python", "Django"])
        assert job.skills == ["Python", "Django"]


class TestRFC822DateParsing:
    def test_parses_valid_rfc822_posting_date(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(pubdate="Tue, 25 Aug 2026 07:31:11 +0000")
        assert job.posting_date == datetime(2026, 8, 25, 7, 31, 11, tzinfo=UTC)

    def test_parses_valid_rfc822_closing_date(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(expires_at="Thu, 24 Sep 2026 07:31:11 +0000")
        assert job.closing_date == datetime(2026, 9, 24, 7, 31, 11, tzinfo=UTC)

    def test_none_date_yields_none(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(pubdate=None, expires_at=None)
        assert job.posting_date is None
        assert job.closing_date is None

    def test_empty_string_date_yields_none(self, make_raw_wwr_job) -> None:
        job = make_raw_wwr_job(pubdate="", expires_at="")
        assert job.posting_date is None
        assert job.closing_date is None

    def test_unparseable_date_string_yields_none_rather_than_raising(
        self, make_raw_wwr_job
    ) -> None:
        # Matches RemoteOK's skip-don't-crash philosophy for dates: a
        # missing date is recoverable, unlike a missing title or URL.
        job = make_raw_wwr_job(pubdate="not a date at all")
        assert job.posting_date is None

    def test_iso8601_date_string_does_not_parse_as_rfc822(self, make_raw_wwr_job) -> None:
        # Confirms this really is a different parser than RemoteOK's --
        # an ISO-8601 string (RemoteOK's format) is not valid RFC 822 and
        # should degrade to None, not silently succeed.
        job = make_raw_wwr_job(pubdate="2026-08-25T07:31:11+00:00")
        assert job.posting_date is None


class TestNoSalaryFields:
    def test_model_has_no_salary_attributes(self) -> None:
        # Structural assertion: RawWWRJob must not carry salary_min/
        # salary_max fields at all -- We Work Remotely's feed has no
        # structured salary data, and inventing placeholder fields here
        # would misrepresent what this source actually provides.
        field_names = set(RawWWRJob.model_fields.keys())
        assert "salary_min" not in field_names
        assert "salary_max" not in field_names


class TestRequiredFieldsAndDefaults:
    def test_minimal_valid_job_uses_defaults_for_everything_else(self) -> None:
        job = RawWWRJob(
            source_job_id="1",
            job_title="Engineer",
            company_name="Acme",
            original_url="https://weworkremotely.com/remote-jobs/1",
        )
        assert job.company_logo_url is None
        assert job.skills == []
        assert job.region_raw is None
        assert job.country_raw is None
        assert job.state_raw is None
        assert job.category_raw is None
        assert job.employment_type_raw is None
        assert job.description_raw is None
        assert job.posting_date is None
        assert job.closing_date is None
        assert job.raw_payload == {}

    @pytest.mark.parametrize("missing_field", ["job_title", "company_name", "original_url"])
    def test_missing_required_field_raises(self, missing_field: str) -> None:
        fields: dict[str, Any] = {
            "source_job_id": "1",
            "job_title": "Engineer",
            "company_name": "Acme",
            "original_url": "https://weworkremotely.com/remote-jobs/1",
        }
        del fields[missing_field]
        with pytest.raises(ValidationError):
            RawWWRJob(**fields)

    def test_raw_payload_is_preserved_unmodified(self, make_raw_wwr_job) -> None:
        raw = {
            "title": "Acme: Engineer",
            "guid": "https://weworkremotely.com/remote-jobs/acme-engineer",
            "link": "https://weworkremotely.com/remote-jobs/acme-engineer",
        }
        job = RawWWRJob.model_validate({**raw, "raw_payload": raw})
        assert job.raw_payload == raw

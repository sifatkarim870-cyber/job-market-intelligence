"""Unit tests for job_market_intel.scrapers.hrge.models.

What these tests verify, and why each matters:
    - ``from_api_entry`` against a payload shaped exactly like the live
      merged list+detail record observed during scoping (2026-10-06/07):
      English taxonomy under ``Accept-Language: en``, slug-less canonical
      URL, city list, logo fallback. The scraper is built on these field
      names, so a silent rename here would empty the database.
    - The anonymity rule: employers who hide their name must still yield
      a NOT NULL company (core.jobs.company_id is NOT NULL downstream).
    - Timestamp parsing: HR.ge serves ISO-8601 with milliseconds and no
      zone (assumed UTC), and an unparseable date must become None
      (validator flags it) rather than crash the record away.
    - Location accepts addresses (detail) with a fallback to the list's
      ``locations``, and tolerates the string form.
    - Required-field validation: an empty title or missing announcementId
      raises ValidationError so the parser can skip, not crash.
"""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.hrge.models import RawHRGeJob


def _live_entry(**overrides):
    """A merged list+detail record as HRGeClient returns it (live shape)."""
    entry = {
        "announcementId": 496982,
        "title": "Online Game Host",
        "customerName": "AMBER STUDIOS",
        "isAnonymous": False,
        "logoFilename": "https://cdn.hr.ge/logo.png",
        "logoUrl": None,
        "publishDate": "2026-10-06T17:17:03.857",
        "deadlineDate": "2026-11-04T19:59:00",
        "addresses": ["Tbilisi"],
        "locations": ["Tbilisi"],
        "salaryFrom": None,
        "salaryTo": None,
        "showSalary": False,
        "hideSalary": None,
        "isWorkFromHome": True,
        "description": "<div>Job body</div>",
        "announcementRequirements": {
            "specializationList": [{"name": "Sales"}, {"name": "Sales"}],
            "industryList": [{"name": "Retail"}],
            "seniorityLevels": ["Mid-Level"],
            "employmentTypeName": "Fixed-term contract",
            "workScheduleName": "Full-time",
        },
        "employmentFormTypeName": "On site",
    }
    entry.update(overrides)
    return entry


class TestFromApiEntry:
    def test_full_live_payload_maps_every_field(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry())
        assert job.source_job_id == "496982"
        assert job.job_title == "Online Game Host"
        assert job.company_name == "AMBER STUDIOS"
        assert job.category_raw == "Sales"
        assert job.industry_raw == "Retail"
        assert job.seniority_raw == "Mid-Level"
        assert job.contract_type_raw == "Fixed-term contract"
        assert job.work_schedule_raw == "Full-time"
        assert job.work_form_raw == "On site"
        assert job.location_raw == "Tbilisi"
        assert job.description_raw == "<div>Job body</div>"
        assert job.is_work_from_home is True

    def test_canonical_url_is_slug_less_announcement_path(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry())
        assert job.original_url == "https://www.hr.ge/announcement/496982"

    def test_tags_come_from_specializations_and_industries_deduplicated(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry())
        # specializationList repeats "Sales"; industry adds "Retail".
        assert job.tags == ["Sales", "Retail"]

    def test_logo_falls_back_from_logo_url_to_logo_filename(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry())
        assert job.company_logo_url == "https://cdn.hr.ge/logo.png"
        job2 = RawHRGeJob.from_api_entry(_live_entry(logoUrl="https://x/y.png"))
        assert job2.company_logo_url == "https://x/y.png"

    def test_location_uses_addresses_then_falls_back_to_locations(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(addresses=["Tbilisi", "Batumi"]))
        assert job.location_raw == "Tbilisi, Batumi"
        job2 = RawHRGeJob.from_api_entry(_live_entry(addresses=None))
        assert job2.location_raw == "Tbilisi"
        job3 = RawHRGeJob.from_api_entry(_live_entry(addresses="Tbilisi"))
        assert job3.location_raw == "Tbilisi"

    def test_missing_customer_name_becomes_anonymous(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(customerName=None))
        assert job.company_name == "Anonymous"

    def test_is_anonymous_forces_anonymous_despite_a_name(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(isAnonymous=True))
        assert job.company_name == "Anonymous"

    def test_missing_requirements_yields_none_taxonomies(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(announcementRequirements=None))
        assert job.category_raw is None
        assert job.contract_type_raw is None
        assert job.tags == []


class TestFieldValidation:
    def test_empty_title_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RawHRGeJob.from_api_entry(_live_entry(title=""))

    def test_missing_announcement_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RawHRGeJob.from_api_entry(_live_entry(announcementId=None))

    def test_numeric_announcement_id_is_stringified(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(announcementId=496982))
        assert job.source_job_id == "496982"


class TestTimestamps:
    def test_naive_millisecond_timestamp_becomes_utc(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry())
        assert job.posting_date is not None
        # Naive (no offset on the wire) -> assumed UTC, as documented.
        assert job.posting_date.tzinfo is UTC
        assert job.posting_date.year == 2026
        assert job.posting_date.month == 10
        assert job.posting_date.day == 6

    def test_unparseable_timestamp_becomes_none_not_a_crash(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(publishDate="not-a-date"))
        assert job.posting_date is None

    def test_absent_timestamp_becomes_none(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(deadlineDate=None))
        assert job.closing_date is None


class TestSalaryCoercion:
    def test_string_salary_bounds_coerce_to_int(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(salaryFrom="1200", salaryTo="1800"))
        assert job.salary_from_raw == 1200
        assert job.salary_to_raw == 1800

    def test_garbage_salary_bounds_become_none(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(salaryFrom="competitive"))
        assert job.salary_from_raw is None

    def test_disclosure_flags_keep_their_types(self) -> None:
        job = RawHRGeJob.from_api_entry(_live_entry(salaryFrom=1200, showSalary=True))
        assert job.show_salary is True
        assert job.salary_from_raw == 1200

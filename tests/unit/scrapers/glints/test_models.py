"""Unit tests for job_market_intel.scrapers.glints.models.

Pins ``from_page_payload``'s contract against both payload shapes
confirmed live (2026-10-07): the full ~67-key ``initialData.data``
record and the 16-key sourced-job fallback with its flattened salary —
including the field-shaping decisions (location chain, JobSkills
extraction, remote flag, date-only expiry) the cleaner depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.glints.models import RawGlintsJob

_CANONICAL_URL = (
    "https://glints.com/id/opportunities/jobs/penjaga-rumah/"
    "94d7e90f-f53b-4718-8601-ff4e7d623725"
)


def _full_record(**overrides) -> dict:
    """The observed full-record shape (Glints "Penjaga Rumah", ID)."""
    record = {
        "id": "94d7e90f-f53b-4718-8601-ff4e7d623725",
        "title": "Penjaga Rumah",
        "CountryCode": "ID",
        "type": "FULL_TIME",
        "status": "OPEN",
        "jobSource": "EMPLOYER",
        "createdAt": "2026-10-06T21:19:26.970737Z",
        "expiryDate": "2026-11-06",
        "shouldShowSalary": True,
        "isRemote": False,
        "workArrangementOption": "ONSITE",
        "externalApplyURL": None,
        "descriptionJsonString": '{"blocks": [{"text": "Kami mencari karyawan"}], "entityMap": {}}',
        "salaries": [
            {
                "CurrencyCode": "IDR",
                "minAmount": 1000000,
                "maxAmount": 2000000,
                "paymentFrequency": None,
                "salaryMode": "MONTH",
                "salaryType": "BASIC",
            }
        ],
        "location": {
            "formattedName": "Penjaringan",
            "name": "Penjaringan",
            "parents": [
                {"formattedName": "Jakarta Utara"},
                {"formattedName": "DKI Jakarta"},
                {"formattedName": "Indonesia"},
            ],
        },
        "hierarchicalJobCategory": {"name": "Store Crew"},
        "company": {
            "brandName": "PT Akari Beauty Group",
            "industry": {"id": 47, "name": "Accounting"},
        },
        "JobSkills": [
            {"mustHave": True, "skill": {"name": "Customer Service"}},
            {"mustHave": False, "skill": {"name": "Retail"}},
        ],
    }
    record.update(overrides)
    return record


class TestFullRecordShape:
    def test_identity_and_core_fields(self) -> None:
        job = RawGlintsJob.from_page_payload(_full_record(), original_url=_CANONICAL_URL)
        assert job.source_job_id == "94d7e90f-f53b-4718-8601-ff4e7d623725"
        assert job.job_title == "Penjaga Rumah"
        assert job.company_name == "PT Akari Beauty Group"
        assert job.country_code == "ID"
        assert job.contract_type_raw == "FULL_TIME"
        assert job.original_url == _CANONICAL_URL

    def test_location_chain_is_nearest_first(self) -> None:
        job = RawGlintsJob.from_page_payload(_full_record(), original_url=_CANONICAL_URL)
        assert job.location_raw == "Penjaringan, Jakarta Utara, DKI Jakarta, Indonesia"

    def test_missing_location_is_none_not_empty(self) -> None:
        job = RawGlintsJob.from_page_payload(
            _full_record(location=None), original_url=_CANONICAL_URL
        )
        assert job.location_raw is None

    def test_salary_list_shape(self) -> None:
        job = RawGlintsJob.from_page_payload(_full_record(), original_url=_CANONICAL_URL)
        assert job.salary_from_raw == 1000000
        assert job.salary_to_raw == 2000000
        assert job.salary_currency == "IDR"
        assert job.salary_mode == "MONTH"
        assert job.should_show_salary is True

    def test_tags_combine_skills_category_and_industry(self) -> None:
        job = RawGlintsJob.from_page_payload(_full_record(), original_url=_CANONICAL_URL)
        assert job.tags == ["Customer Service", "Retail", "Store Crew", "Accounting"]

    def test_job_skills_null_falls_back_to_category_and_industry(self) -> None:
        job = RawGlintsJob.from_page_payload(
            _full_record(JobSkills=None), original_url=_CANONICAL_URL
        )
        assert job.tags == ["Store Crew", "Accounting"]

    def test_dates_parse_including_date_only_expiry(self) -> None:
        job = RawGlintsJob.from_page_payload(_full_record(), original_url=_CANONICAL_URL)
        assert job.posting_date == datetime(2026, 10, 6, 21, 19, 26, 970737, tzinfo=UTC)
        assert job.closing_date == datetime(2026, 11, 6, tzinfo=UTC)

    def test_remote_flag_from_arrangement(self) -> None:
        job = RawGlintsJob.from_page_payload(
            _full_record(workArrangementOption="REMOTE", isRemote=False),
            original_url=_CANONICAL_URL,
        )
        assert job.is_work_from_home is True

    def test_onsite_job_is_not_remote(self) -> None:
        job = RawGlintsJob.from_page_payload(_full_record(), original_url=_CANONICAL_URL)
        assert job.is_work_from_home is False


class TestSourcedFallbackShape:
    def test_flat_salary_shape_is_accepted(self) -> None:
        record = {
            "id": "03d2a8e4-c473-4a24-88ed-3e3980aadc0f",
            "title": "Senior HR&GA",
            "type": "FULL_TIME",
            "createdAt": "2026-09-08T00:24:34.455333Z",
            "descriptionJsonString": '{"blocks": [{"text": "We are hiring"}], "entityMap": {}}',
            "minSalary": 8000000,
            "maxSalary": 12000000,
            "salaryCurrencyCode": "IDR",
            "company": {"name": "Sourced Co"},
        }
        job = RawGlintsJob.from_page_payload(
            record,
            original_url="https://glints.com/id/opportunities/s/senior-hr-and-ga/"
            "03d2a8e4-c473-4a24-88ed-3e3980aadc0f",
        )
        assert job.salary_from_raw == 8000000
        assert job.salary_to_raw == 12000000
        assert job.salary_currency == "IDR"
        assert job.location_raw is None
        assert job.category_raw is None
        assert job.status is None

    def test_company_name_falls_back_to_name_key(self) -> None:
        record = {"id": "x", "title": "T", "company": {"name": "Plain Name"}}
        job = RawGlintsJob.from_page_payload(
            record, original_url="https://glints.com/id/opportunities/s/t/x"
        )
        assert job.company_name == "Plain Name"

    def test_missing_company_becomes_anonymous(self) -> None:
        job = RawGlintsJob.from_page_payload(
            {"id": "x", "title": "T"}, original_url="https://glints.com/id/opportunities/s/t/x"
        )
        assert job.company_name == "Anonymous"


class TestRequiredIdentity:
    @pytest.mark.parametrize("bad", [{"title": "T"}, {"id": ""}, {"id": None, "title": "T"}])
    def test_missing_id_is_a_validation_error(self, bad: dict) -> None:
        with pytest.raises(ValidationError):
            RawGlintsJob.from_page_payload(bad, original_url=_CANONICAL_URL)

    @pytest.mark.parametrize("bad", [{"id": "x"}, {"id": "x", "title": ""}])
    def test_missing_title_is_a_validation_error(self, bad: dict) -> None:
        with pytest.raises(ValidationError):
            RawGlintsJob.from_page_payload(bad, original_url=_CANONICAL_URL)

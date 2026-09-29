"""Unit tests for job_market_intel.scrapers.reed.models.RawReedJob."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.reed.models import RawReedJob

SEARCH_RECORD = {
    "jobId": 57364884,
    "employerName": "Norton Rose Fulbright LLP",
    "jobTitle": "AI Engineer",
    "locationName": "London",
    "minimumSalary": None,
    "maximumSalary": None,
    "currency": None,
    "date": "18/09/2026",
    "expirationDate": "30/10/2026",
    "jobDescription": "Short excerpt...",
    "jobUrl": "https://www.reed.co.uk/jobs/ai-engineer/57364884",
}

DETAILS_RECORD = {
    "jobId": 57364884,
    "minimumSalary": 450.0,
    "maximumSalary": 600.0,
    "currency": "GBP",
    "salaryType": "per day",
    "datePosted": "18/09/2026",
    "expirationDate": "30/10/2026",
    "externalUrl": "https://employer.example/apply/57364884",
    "partTime": False,
    "fullTime": True,
    "contractType": "Permanent",
    "jobDescription": "Full HTML description...",
}


class TestFromCombinedRequiredFields:
    def test_builds_successfully_with_search_and_details(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.source_job_id == "57364884"
        assert job.job_title == "AI Engineer"
        assert job.company_name == "Norton Rose Fulbright LLP"

    def test_missing_job_title_raises(self) -> None:
        broken = {**SEARCH_RECORD, "jobTitle": ""}
        with pytest.raises(ValidationError):
            RawReedJob.from_combined(broken, DETAILS_RECORD)

    def test_missing_original_url_raises(self) -> None:
        broken = {**SEARCH_RECORD, "jobUrl": ""}
        with pytest.raises(ValidationError):
            RawReedJob.from_combined(broken, DETAILS_RECORD)


class TestDetailsPreferredOverSearch:
    """Confirmed live: Details carries the real currency/salaryType/
    contractType/fullTime/partTime/externalUrl; Search reliably does not."""

    def test_currency_comes_from_details(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.currency_iso_code == "GBP"

    def test_pay_period_raw_comes_from_details(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.pay_period_raw == "per day"

    def test_contract_type_and_hours_come_from_details(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.contract_type_raw == "Permanent"
        assert job.full_time is True
        assert job.part_time is False

    def test_apply_url_comes_from_details_external_url(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.apply_url == "https://employer.example/apply/57364884"

    def test_fuller_description_from_details_is_preferred(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.description_raw == "Full HTML description..."


class TestDetailsAbsent:
    """Details is None only in test scenarios today (see pipeline.py's
    module docstring for why the real pipeline never reaches here with
    details=None) -- must still behave sanely for testability."""

    def test_details_only_fields_are_none(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, None)
        assert job.currency_iso_code is None
        assert job.pay_period_raw is None
        assert job.contract_type_raw is None
        assert job.full_time is None
        assert job.part_time is None
        assert job.apply_url is None

    def test_falls_back_to_search_description(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, None)
        assert job.description_raw == "Short excerpt..."


class TestDateParsing:
    def test_parses_dd_mm_yyyy(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.posting_date == datetime(2026, 9, 18, tzinfo=UTC)
        assert job.closing_date == datetime(2026, 10, 30, tzinfo=UTC)

    def test_unparseable_date_becomes_none_not_an_error(self) -> None:
        broken = {**SEARCH_RECORD, "date": "not-a-date"}
        job = RawReedJob.from_combined(broken, None)
        assert job.posting_date is None

    def test_missing_date_becomes_none(self) -> None:
        broken = {**SEARCH_RECORD, "date": None}
        job = RawReedJob.from_combined(broken, None)
        assert job.posting_date is None


class TestRawPayloadPreservesBothResponses:
    def test_raw_payload_keeps_search_and_details_separately(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, DETAILS_RECORD)
        assert job.raw_payload["search"] == SEARCH_RECORD
        assert job.raw_payload["details"] == DETAILS_RECORD

    def test_raw_payload_details_is_none_when_details_absent(self) -> None:
        job = RawReedJob.from_combined(SEARCH_RECORD, None)
        assert job.raw_payload["details"] is None

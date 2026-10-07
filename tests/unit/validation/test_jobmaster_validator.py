"""Unit tests for job_market_intel.validation.jobmaster_validator.

Pins the threshold contract (50-row floor, 10% skip-rate ceiling) and
the JobMaster missing-field checks, same pattern as the other
sources' validator tests. Raw jobs come from the
``make_raw_jobmaster_job`` conftest factory.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from job_market_intel.scrapers.jobmaster.models import RawJobmasterJob
from job_market_intel.validation.jobmaster_validator import (
    JobmasterBatchValidator,
)


def _batch(n: int, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]) -> list[RawJobmasterJob]:
    """N parsed jobs with distinct ids (duplicates would be their own issue)."""
    return [make_raw_jobmaster_job(source_job_id=str(1000 + i)) for i in range(n)]


class TestThresholds:
    def test_healthy_batch_passes(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        jobs = _batch(50, make_raw_jobmaster_job)
        report = JobmasterBatchValidator().validate([{}] * 50, jobs)
        assert report.passed is True
        assert report.issues == []
        assert report.total_parsed == 50

    def test_below_minimum_fails(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        jobs = _batch(49, make_raw_jobmaster_job)
        report = JobmasterBatchValidator().validate([{}] * 49, jobs)
        assert report.passed is False
        assert any("minimum of 50" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = JobmasterBatchValidator().validate([], [])
        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)

    def test_skip_rate_ceiling(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        jobs = _batch(50, make_raw_jobmaster_job)
        report = JobmasterBatchValidator().validate([{}] * 50, jobs[:44])
        assert report.passed is False
        assert any("Skip rate" in issue for issue in report.issues)


class TestMissingFieldChecks:
    def test_missing_field_rates_reflect_jobmaster_checks(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        bare = make_raw_jobmaster_job(
            description_html=None,
            location_text=None,
            category_raws=[],
            work_type_label=None,
            salary_text=None,
        )
        report = JobmasterBatchValidator().validate([{}, {}], [bare, bare])
        # Informational rates; a missing optional field never fails the
        # batch by itself (the pipeline treats validation as flag-only).
        assert report.missing_field_rates["location_text"] == pytest.approx(1.0)
        assert report.missing_field_rates["description_html"] == pytest.approx(1.0)
        assert report.missing_field_rates["category_raws"] == pytest.approx(1.0)
        assert report.missing_field_rates["work_type_label"] == pytest.approx(1.0)
        assert report.missing_field_rates["salary_disclosure"] == pytest.approx(1.0)

    def test_healthy_job_has_zero_missing_rates(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        jobs = [
            make_raw_jobmaster_job(),
            make_raw_jobmaster_job(source_job_id="9884961"),
        ]
        report = JobmasterBatchValidator().validate([{}, {}], jobs)
        assert report.missing_field_rates == {
            "location_text": 0.0,
            "description_html": 0.0,
            "posting_date": 0.0,
            "category_raws": 0.0,
            "work_type_label": 0.0,
            "salary_disclosure": 0.0,
        }

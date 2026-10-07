"""Unit tests for job_market_intel.validation.irantalent_validator.

Pins the threshold contract (100-row floor, 10% skip-rate ceiling) and
the Irantalent missing-field checks, same pattern as the other sources'
validator tests. Raw jobs come from the ``make_raw_irantalent_job``
conftest factory (live row 184579 snapshot).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from job_market_intel.scrapers.irantalent.models import RawIrantalentJob
from job_market_intel.validation.irantalent_validator import (
    IrantalentBatchValidator,
    IrantalentValidationSettings,
)


def _batch(
    n: int, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
) -> list[RawIrantalentJob]:
    """N parsed jobs with distinct ids (duplicates would be their own issue)."""
    return [make_raw_irantalent_job(source_job_id=str(1000 + i)) for i in range(n)]


class TestThresholds:
    def test_healthy_batch_passes(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        jobs = _batch(100, make_raw_irantalent_job)
        report = IrantalentBatchValidator().validate([{}] * 100, jobs)
        assert report.passed is True
        assert report.issues == []
        assert report.total_parsed == 100

    def test_below_minimum_fails(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        jobs = _batch(99, make_raw_irantalent_job)
        report = IrantalentBatchValidator().validate([{}] * 99, jobs)
        assert report.passed is False
        assert any("minimum of 100" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = IrantalentBatchValidator().validate([], [])
        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)

    def test_skip_rate_ceiling(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        # 100 raw, 89 parsed = 11% skip > the 10% ceiling (parsed can
        # never exceed raw, so the batch is modeled the real way).
        jobs = _batch(100, make_raw_irantalent_job)
        report = IrantalentBatchValidator().validate([{}] * 100, jobs[:89])
        assert report.passed is False
        assert any("Skip rate" in issue for issue in report.issues)


class TestMissingFieldChecks:
    def test_missing_field_rates_reflect_irantalent_checks(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        bare = make_raw_irantalent_job(
            description_html=None,
            location_text=None,
            category_raws=[],
            industry_raws=[],
            salary_min_raw=None,
            salary_max_raw=None,
            salary_show_flag=None,
        )
        report = IrantalentBatchValidator().validate([{}, {}], [bare, bare])
        # Informational rates — a missing optional field never fails
        # the batch by itself (the pipeline treats validation as
        # flag-only, per pipeline.py).
        assert report.missing_field_rates["location_text"] == pytest.approx(1.0)
        assert report.missing_field_rates["description_html"] == pytest.approx(1.0)
        assert report.missing_field_rates["skills_tags"] == pytest.approx(1.0)
        assert report.missing_field_rates["salary_disclosure"] == pytest.approx(1.0)

    def test_healthy_job_has_zero_missing_rates(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        jobs = [
            make_raw_irantalent_job(),
            make_raw_irantalent_job(source_job_id="2001"),
        ]
        report = IrantalentBatchValidator().validate([{}, {}], jobs)
        assert report.missing_field_rates == {
            "location_text": 0.0,
            "description_html": 0.0,
            "posting_date": 0.0,
            "skills_tags": 0.0,
            "work_type": 0.0,
            "salary_disclosure": 0.0,
        }


def test_thresholds_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
    make_raw_irantalent_job: Callable[..., RawIrantalentJob],
) -> None:
    monkeypatch.setenv("IRANTALENT_VALIDATION_MIN_EXPECTED_JOBS", "2")
    settings = IrantalentValidationSettings()
    assert settings.min_expected_jobs == 2

    jobs = _batch(3, make_raw_irantalent_job)
    report = IrantalentBatchValidator(settings=settings).validate([{}] * 3, jobs)
    assert report.passed is True  # 3 >= 2, no skips, distinct ids

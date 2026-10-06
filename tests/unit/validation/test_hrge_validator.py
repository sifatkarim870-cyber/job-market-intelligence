"""Unit tests for job_market_intel.validation.hrge_validator.

Thin wrapper around the shared batch-health engine, so the tests pin
HR.ge's own configuration: a healthy run is in the hundreds (the live
site reports ~3,596 active vacancies; even a deliberately capped
single-page run fetches 100), and the thresholds are env-overridable.
"""

from __future__ import annotations

from job_market_intel.validation.hrge_validator import (
    HRGeBatchValidator,
    HRGeValidationSettings,
)


class TestSettings:
    def test_defaults(self) -> None:
        settings = HRGeValidationSettings()
        assert settings.min_expected_jobs == 100
        assert settings.max_skip_rate == 0.10

    def test_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("HRGE_VALIDATION_MIN_EXPECTED_JOBS", "2")
        assert HRGeValidationSettings().min_expected_jobs == 2


class TestValidate:
    def test_healthy_batch_passes(self, make_raw_hrge_job) -> None:
        validator = HRGeBatchValidator(
            settings=HRGeValidationSettings(min_expected_jobs=2)
        )
        parsed = [make_raw_hrge_job(), make_raw_hrge_job(source_job_id="2")]
        report = validator.validate([{}, {}], parsed)
        assert report.passed is True
        assert report.issues == []

    def test_below_minimum_fails(self, make_raw_hrge_job) -> None:
        validator = HRGeBatchValidator(
            settings=HRGeValidationSettings(min_expected_jobs=10)
        )
        parsed = [make_raw_hrge_job(), make_raw_hrge_job(source_job_id="2")]
        report = validator.validate([{}, {}], parsed)
        assert report.passed is False
        assert any("minimum" in issue for issue in report.issues)

    def test_excessive_skip_rate_fails(self, make_raw_hrge_job) -> None:
        validator = HRGeBatchValidator(
            settings=HRGeValidationSettings(min_expected_jobs=1, max_skip_rate=0.10)
        )
        parsed = [make_raw_hrge_job()]
        report = validator.validate([{}, {}, {}, {}], parsed)  # 75% skipped
        assert report.passed is False
        assert any("Skip rate" in issue for issue in report.issues)

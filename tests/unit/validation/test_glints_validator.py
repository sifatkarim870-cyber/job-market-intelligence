"""Unit tests for job_market_intel.validation.glints_validator.

Same three contracts every source's validator tests pin down: healthy
batches pass, too-small batches fail on the minimum, and excessive
skip rates fail — with Glints' own thresholds/field checks.
"""

from __future__ import annotations

from job_market_intel.validation.glints_validator import (
    GlintsBatchValidator,
    GlintsValidationSettings,
)


class TestSettings:
    def test_defaults_are_sane(self) -> None:
        settings = GlintsValidationSettings()
        assert 0.0 <= settings.max_skip_rate <= 1.0
        assert settings.min_expected_jobs >= 0

    def test_env_prefix(self, monkeypatch) -> None:
        monkeypatch.setenv("GLINTS_VALIDATION_MIN_EXPECTED_JOBS", "2")
        assert GlintsValidationSettings().min_expected_jobs == 2


class TestValidateBatch:
    def test_healthy_batch_passes(self, make_raw_glints_job) -> None:
        validator = GlintsBatchValidator(
            settings=GlintsValidationSettings(min_expected_jobs=2)
        )
        raw = [{}, {}]
        parsed = [make_raw_glints_job(), make_raw_glints_job(
            source_job_id="22222222-2222-2222-2222-222222222222"
        )]
        report = validator.validate(raw, parsed)
        assert report.passed
        assert not report.issues

    def test_below_minimum_fails(self, make_raw_glints_job) -> None:
        validator = GlintsBatchValidator(
            settings=GlintsValidationSettings(min_expected_jobs=10)
        )
        report = validator.validate([{}, {}], [make_raw_glints_job()])
        assert not report.passed

    def test_excessive_skip_rate_fails(self, make_raw_glints_job) -> None:
        validator = GlintsBatchValidator(
            settings=GlintsValidationSettings(min_expected_jobs=1, max_skip_rate=0.10)
        )
        # 1 parsed of 10 raw = 90% skipped > 10% ceiling.
        report = validator.validate([{}] * 10, [make_raw_glints_job()])
        assert not report.passed

    def test_missing_field_rates_are_reported(self, make_raw_glints_job) -> None:
        validator = GlintsBatchValidator(
            settings=GlintsValidationSettings(min_expected_jobs=1, max_skip_rate=1.0)
        )
        stripped = make_raw_glints_job(
            location_raw=None,
            description_raw=None,
            tags=[],
            posting_date=None,
            contract_type_raw=None,
        )
        report = validator.validate([{}], [stripped])
        # Missing-field rates are report DATA (not pass/fail issues) —
        # the same stance the other sources take.
        for field in ("location_raw", "description_raw", "tags",
                      "posting_date", "contract_type_raw"):
            assert report.missing_field_rates[field] == 1.0

    def test_healthy_job_has_zero_missing_rates(self, make_raw_glints_job) -> None:
        validator = GlintsBatchValidator(
            settings=GlintsValidationSettings(min_expected_jobs=1, max_skip_rate=1.0)
        )
        report = validator.validate([{}], [make_raw_glints_job()])
        assert all(rate == 0.0 for rate in report.missing_field_rates.values())

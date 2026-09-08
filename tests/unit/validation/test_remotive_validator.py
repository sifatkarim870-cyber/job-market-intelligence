"""Unit tests for job_market_intel.validation.remotive_validator.

Mirrors ``validation/test_remoteok_validator.py``'s coverage and rationale
exactly — see that module's docstring for why each check matters. This is
a thin wrapper around the shared ``validate_batch``, so these tests exist
mainly to confirm Remotive's own thresholds and missing-field checks are
wired correctly, not to re-test ``validate_batch`` itself (that's
``validation/test_common.py``'s job).
"""

from __future__ import annotations

from job_market_intel.validation.remotive_validator import (
    RemotiveBatchValidator,
    RemotiveValidationSettings,
)

# The RawRemotiveJob factory used below (`make_raw_remotive_job`) is the
# shared, root-level fixture in tests/conftest.py.

# A permissive settings instance so tests about OTHER checks don't
# accidentally also trip the min_expected_jobs threshold at small batch sizes.
_LENIENT_SETTINGS = RemotiveValidationSettings(min_expected_jobs=1, max_skip_rate=0.50)


class TestHealthyBatch:
    def test_healthy_batch_passes_with_no_issues(self, make_raw_remotive_job) -> None:
        raw_jobs = [{"id": i} for i in range(25)]
        parsed_jobs = [make_raw_remotive_job(id=i) for i in range(25)]

        report = RemotiveBatchValidator(settings=RemotiveValidationSettings()).validate(
            raw_jobs, parsed_jobs
        )

        assert report.passed is True
        assert report.issues == []
        assert report.total_raw_records == 25
        assert report.total_parsed == 25
        assert report.total_skipped == 0
        assert report.skip_rate == 0.0
        assert report.duplicate_source_job_ids == []


class TestVolumeSanity:
    def test_too_few_parsed_jobs_is_flagged(self, make_raw_remotive_job) -> None:
        settings = RemotiveValidationSettings(min_expected_jobs=20, max_skip_rate=0.50)
        raw_jobs = [{"id": i} for i in range(5)]
        parsed_jobs = [make_raw_remotive_job(id=i) for i in range(5)]

        report = RemotiveBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_is_its_own_issue(self) -> None:
        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])

        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)
        assert report.skip_rate == 0.0  # must not raise ZeroDivisionError

    def test_exactly_at_minimum_passes_the_volume_check(self, make_raw_remotive_job) -> None:
        settings = RemotiveValidationSettings(min_expected_jobs=10, max_skip_rate=0.50)
        raw_jobs = [{"id": i} for i in range(10)]
        parsed_jobs = [make_raw_remotive_job(id=i) for i in range(10)]

        report = RemotiveBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert not any("below the configured minimum" in issue for issue in report.issues)


class TestSkipRateSanity:
    def test_high_skip_rate_is_flagged(self, make_raw_remotive_job) -> None:
        settings = RemotiveValidationSettings(min_expected_jobs=1, max_skip_rate=0.10)
        # 10 raw, only 5 parsed -> 50% skip rate, well above the 10% max.
        raw_jobs = [{"id": i} for i in range(10)]
        parsed_jobs = [make_raw_remotive_job(id=i) for i in range(5)]

        report = RemotiveBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert report.skip_rate == 0.5
        assert any("Skip rate" in issue for issue in report.issues)

    def test_skip_rate_within_threshold_does_not_flag(self, make_raw_remotive_job) -> None:
        settings = RemotiveValidationSettings(min_expected_jobs=1, max_skip_rate=0.20)
        raw_jobs = [{"id": i} for i in range(10)]
        parsed_jobs = [make_raw_remotive_job(id=i) for i in range(9)]  # 10% skip rate

        report = RemotiveBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert not any("Skip rate" in issue for issue in report.issues)


class TestDuplicateDetection:
    def test_duplicate_source_job_ids_are_detected_and_named(self, make_raw_remotive_job) -> None:
        parsed_jobs = [
            make_raw_remotive_job(id=1),
            make_raw_remotive_job(id=2),
            make_raw_remotive_job(id=1),  # "1" appears twice
        ]
        raw_jobs = [{"id": 1}, {"id": 2}, {"id": 1}]

        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert report.duplicate_source_job_ids == ["1"]
        assert any("duplicate source_job_id" in issue for issue in report.issues)

    def test_no_duplicates_in_normal_batch(self, make_raw_remotive_job) -> None:
        parsed_jobs = [make_raw_remotive_job(id=i) for i in range(5)]
        raw_jobs = [{"id": i} for i in range(5)]

        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.duplicate_source_job_ids == []


class TestMissingFieldRates:
    def test_missing_field_rates_computed_correctly(self, make_raw_remotive_job) -> None:
        parsed_jobs = [
            make_raw_remotive_job(id=1, candidate_required_location=None, salary=None, tags=[]),
            make_raw_remotive_job(id=2),  # has everything
        ]
        raw_jobs = [{"id": 1}, {"id": 2}]

        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.missing_field_rates["location_raw"] == 0.5
        assert report.missing_field_rates["salary"] == 0.5
        assert report.missing_field_rates["description_raw"] == 0.0
        assert report.missing_field_rates["tags"] == 0.5
        assert report.missing_field_rates["posting_date"] == 0.0

    def test_missing_field_rates_are_zero_not_error_on_empty_batch(self) -> None:
        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])

        assert all(rate == 0.0 for rate in report.missing_field_rates.values())

    def test_empty_tags_list_counts_as_missing(self, make_raw_remotive_job) -> None:
        parsed_jobs = [make_raw_remotive_job(id=1, tags=[])]
        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate(
            [{"id": 1}], parsed_jobs
        )

        assert report.missing_field_rates["tags"] == 1.0

    def test_unparseable_salary_text_counts_as_missing(self, make_raw_remotive_job) -> None:
        # "Competitive" is a genuine value Remotive sent, but since
        # RawRemotiveJob's conservative parser leaves salary_min/max as
        # None for it (see models.py), it correctly shows as "missing"
        # here too — same honest signal noted in the cleaner's tests.
        parsed_jobs = [make_raw_remotive_job(id=1, salary="Competitive")]
        report = RemotiveBatchValidator(settings=_LENIENT_SETTINGS).validate(
            [{"id": 1}], parsed_jobs
        )

        assert report.missing_field_rates["salary"] == 1.0

"""Unit tests for job_market_intel.validation.remoteok_validator.

What these tests verify, and why each matters:
    - A healthy batch (plenty of jobs, low skip rate, no duplicates)
      produces passed=True and an empty issues list.
    - Too few parsed jobs is flagged, using a configured threshold rather
      than a hardcoded one, so tests don't depend on RemoteOK's real
      day-to-day job count.
    - A high skip rate is flagged.
    - Duplicate source_job_id values within one batch are detected and
      named.
    - Missing-field rates are computed correctly and never raise on an
      empty parsed-jobs list (division-by-zero guard).
    - Zero raw records is its own distinct issue (not just "too few").
"""

from __future__ import annotations

from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob
from job_market_intel.validation.remoteok_validator import (
    RemoteOKBatchValidator,
    RemoteOKValidationSettings,
)


def _make_job(job_id: str, **overrides: object) -> RawRemoteOKJob:
    """Build a minimally valid RawRemoteOKJob, with any field overridable."""
    defaults: dict[str, object] = {
        "id": job_id,
        "position": "Engineer",
        "company": "Acme",
        "url": f"https://x.test/{job_id}",
        "location": "Worldwide",
        "salary_min": 100000,
        "salary_max": 150000,
        "description": "<p>Do engineering things.</p>",
        "tags": ["python"],
        "date": "2026-01-15T09:00:00+00:00",
    }
    defaults.update(overrides)
    return RawRemoteOKJob.model_validate(defaults)


# A permissive settings instance so tests about OTHER checks don't
# accidentally also trip the min_expected_jobs threshold at small batch sizes.
_LENIENT_SETTINGS = RemoteOKValidationSettings(min_expected_jobs=1, max_skip_rate=0.50)


class TestHealthyBatch:
    def test_healthy_batch_passes_with_no_issues(self) -> None:
        raw_jobs = [{"id": str(i)} for i in range(25)]
        parsed_jobs = [_make_job(str(i)) for i in range(25)]

        report = RemoteOKBatchValidator(settings=RemoteOKValidationSettings()).validate(
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
    def test_too_few_parsed_jobs_is_flagged(self) -> None:
        settings = RemoteOKValidationSettings(min_expected_jobs=20, max_skip_rate=0.50)
        raw_jobs = [{"id": str(i)} for i in range(5)]
        parsed_jobs = [_make_job(str(i)) for i in range(5)]

        report = RemoteOKBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_is_its_own_issue(self) -> None:
        report = RemoteOKBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])

        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)
        assert report.skip_rate == 0.0  # must not raise ZeroDivisionError

    def test_exactly_at_minimum_passes_the_volume_check(self) -> None:
        settings = RemoteOKValidationSettings(min_expected_jobs=10, max_skip_rate=0.50)
        raw_jobs = [{"id": str(i)} for i in range(10)]
        parsed_jobs = [_make_job(str(i)) for i in range(10)]

        report = RemoteOKBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert not any("below the configured minimum" in issue for issue in report.issues)


class TestSkipRateSanity:
    def test_high_skip_rate_is_flagged(self) -> None:
        settings = RemoteOKValidationSettings(min_expected_jobs=1, max_skip_rate=0.10)
        # 10 raw, only 5 parsed -> 50% skip rate, well above the 10% max.
        raw_jobs = [{"id": str(i)} for i in range(10)]
        parsed_jobs = [_make_job(str(i)) for i in range(5)]

        report = RemoteOKBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert report.skip_rate == 0.5
        assert any("Skip rate" in issue for issue in report.issues)

    def test_skip_rate_within_threshold_does_not_flag(self) -> None:
        settings = RemoteOKValidationSettings(min_expected_jobs=1, max_skip_rate=0.20)
        raw_jobs = [{"id": str(i)} for i in range(10)]
        parsed_jobs = [_make_job(str(i)) for i in range(9)]  # 10% skip rate

        report = RemoteOKBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert not any("Skip rate" in issue for issue in report.issues)


class TestDuplicateDetection:
    def test_duplicate_source_job_ids_are_detected_and_named(self) -> None:
        parsed_jobs = [_make_job("1"), _make_job("2"), _make_job("1")]  # "1" appears twice
        raw_jobs = [{"id": "1"}, {"id": "2"}, {"id": "1"}]

        report = RemoteOKBatchValidator(settings=_LENIENT_SETTINGS).validate(
            raw_jobs, parsed_jobs
        )

        assert report.passed is False
        assert report.duplicate_source_job_ids == ["1"]
        assert any("duplicate source_job_id" in issue for issue in report.issues)

    def test_no_duplicates_in_normal_batch(self) -> None:
        parsed_jobs = [_make_job(str(i)) for i in range(5)]
        raw_jobs = [{"id": str(i)} for i in range(5)]

        report = RemoteOKBatchValidator(settings=_LENIENT_SETTINGS).validate(
            raw_jobs, parsed_jobs
        )

        assert report.duplicate_source_job_ids == []


class TestMissingFieldRates:
    def test_missing_field_rates_computed_correctly(self) -> None:
        parsed_jobs = [
            _make_job("1", location=None, salary_min=None, salary_max=None),
            _make_job("2"),  # has everything
        ]
        raw_jobs = [{"id": "1"}, {"id": "2"}]

        report = RemoteOKBatchValidator(settings=_LENIENT_SETTINGS).validate(
            raw_jobs, parsed_jobs
        )

        assert report.missing_field_rates["location_raw"] == 0.5
        assert report.missing_field_rates["salary"] == 0.5
        assert report.missing_field_rates["description_raw"] == 0.0
        assert report.missing_field_rates["tags"] == 0.0
        assert report.missing_field_rates["posting_date"] == 0.0

    def test_missing_field_rates_are_zero_not_error_on_empty_batch(self) -> None:
        report = RemoteOKBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])

        assert all(rate == 0.0 for rate in report.missing_field_rates.values())

    def test_empty_tags_list_counts_as_missing(self) -> None:
        parsed_jobs = [_make_job("1", tags=[])]
        report = RemoteOKBatchValidator(settings=_LENIENT_SETTINGS).validate(
            [{"id": "1"}], parsed_jobs
        )

        assert report.missing_field_rates["tags"] == 1.0

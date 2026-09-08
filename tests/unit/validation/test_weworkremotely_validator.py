"""Unit tests for job_market_intel.validation.weworkremotely_validator.

Mirrors ``validation/test_remoteok_validator.py``'s structure and
reasoning exactly for every check shared with RemoteOK's validator
(healthy batch, volume sanity, skip-rate sanity, duplicate detection,
missing-field rates never raising on an empty batch). The one
substantive difference: the set of fields checked for "missing-field
rate" — no "salary" entry (WWR structurally never has one — see
``weworkremotely_validator.py``'s module docstring for why), plus two
fields RemoteOK's checks never had (``company_logo_url``,
``closing_date``).
"""

from __future__ import annotations

from job_market_intel.validation.weworkremotely_validator import (
    WWRBatchValidator,
    WWRValidationSettings,
)

# The RawWWRJob factory used below (`make_raw_wwr_job`) is the shared,
# root-level fixture in tests/conftest.py.

# A permissive settings instance so tests about OTHER checks don't
# accidentally also trip the min_expected_jobs threshold at small batch sizes.
_LENIENT_SETTINGS = WWRValidationSettings(min_expected_jobs=1, max_skip_rate=0.50)


def _guid(i: int) -> str:
    return f"https://weworkremotely.com/remote-jobs/job-{i}"


class TestHealthyBatch:
    def test_healthy_batch_passes_with_no_issues(self, make_raw_wwr_job) -> None:
        raw_jobs = [{"guid": _guid(i)} for i in range(25)]
        parsed_jobs = [make_raw_wwr_job(guid=_guid(i), link=_guid(i)) for i in range(25)]

        report = WWRBatchValidator(settings=WWRValidationSettings()).validate(raw_jobs, parsed_jobs)

        assert report.passed is True
        assert report.issues == []
        assert report.total_raw_records == 25
        assert report.total_parsed == 25
        assert report.total_skipped == 0
        assert report.skip_rate == 0.0
        assert report.duplicate_source_job_ids == []


class TestVolumeSanity:
    def test_too_few_parsed_jobs_is_flagged(self, make_raw_wwr_job) -> None:
        settings = WWRValidationSettings(min_expected_jobs=20, max_skip_rate=0.50)
        raw_jobs = [{"guid": _guid(i)} for i in range(5)]
        parsed_jobs = [make_raw_wwr_job(guid=_guid(i), link=_guid(i)) for i in range(5)]

        report = WWRBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_is_its_own_issue(self) -> None:
        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])

        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)
        assert report.skip_rate == 0.0  # must not raise ZeroDivisionError

    def test_exactly_at_minimum_passes_the_volume_check(self, make_raw_wwr_job) -> None:
        settings = WWRValidationSettings(min_expected_jobs=10, max_skip_rate=0.50)
        raw_jobs = [{"guid": _guid(i)} for i in range(10)]
        parsed_jobs = [make_raw_wwr_job(guid=_guid(i), link=_guid(i)) for i in range(10)]

        report = WWRBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert not any("below the configured minimum" in issue for issue in report.issues)


class TestSkipRateSanity:
    def test_high_skip_rate_is_flagged(self, make_raw_wwr_job) -> None:
        settings = WWRValidationSettings(min_expected_jobs=1, max_skip_rate=0.10)
        # 10 raw, only 5 parsed -> 50% skip rate, well above the 10% max.
        raw_jobs = [{"guid": _guid(i)} for i in range(10)]
        parsed_jobs = [make_raw_wwr_job(guid=_guid(i), link=_guid(i)) for i in range(5)]

        report = WWRBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert report.skip_rate == 0.5
        assert any("Skip rate" in issue for issue in report.issues)

    def test_skip_rate_within_threshold_does_not_flag(self, make_raw_wwr_job) -> None:
        settings = WWRValidationSettings(min_expected_jobs=1, max_skip_rate=0.20)
        raw_jobs = [{"guid": _guid(i)} for i in range(10)]
        parsed_jobs = [make_raw_wwr_job(guid=_guid(i), link=_guid(i)) for i in range(9)]  # 10% skip

        report = WWRBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert not any("Skip rate" in issue for issue in report.issues)


class TestDuplicateDetection:
    def test_duplicate_source_job_ids_are_detected_and_named(self, make_raw_wwr_job) -> None:
        parsed_jobs = [
            make_raw_wwr_job(guid=_guid(1), link=_guid(1)),
            make_raw_wwr_job(guid=_guid(2), link=_guid(2)),
            make_raw_wwr_job(guid=_guid(1), link=_guid(1)),  # job-1 appears twice
        ]
        raw_jobs = [{"guid": _guid(1)}, {"guid": _guid(2)}, {"guid": _guid(1)}]

        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert report.duplicate_source_job_ids == ["job-1"]
        assert any("duplicate source_job_id" in issue for issue in report.issues)

    def test_no_duplicates_in_normal_batch(self, make_raw_wwr_job) -> None:
        parsed_jobs = [make_raw_wwr_job(guid=_guid(i), link=_guid(i)) for i in range(5)]
        raw_jobs = [{"guid": _guid(i)} for i in range(5)]

        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.duplicate_source_job_ids == []


class TestMissingFieldRates:
    def test_missing_field_rates_computed_correctly(self, make_raw_wwr_job) -> None:
        parsed_jobs = [
            make_raw_wwr_job(
                guid=_guid(1),
                link=_guid(1),
                country="",
                skills="",
                media_content_url=None,
            ),
            make_raw_wwr_job(guid=_guid(2), link=_guid(2)),  # has everything
        ]
        raw_jobs = [{"guid": _guid(1)}, {"guid": _guid(2)}]

        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.missing_field_rates["country_raw"] == 0.5
        assert report.missing_field_rates["skills"] == 0.5
        assert report.missing_field_rates["description_raw"] == 0.0
        assert report.missing_field_rates["posting_date"] == 0.0
        assert report.missing_field_rates["closing_date"] == 0.0
        assert report.missing_field_rates["company_logo_url"] == 0.5

    def test_missing_field_rates_are_zero_not_error_on_empty_batch(self) -> None:
        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])

        assert all(rate == 0.0 for rate in report.missing_field_rates.values())

    def test_empty_skills_list_counts_as_missing(self, make_raw_wwr_job) -> None:
        parsed_jobs = [make_raw_wwr_job(guid=_guid(1), link=_guid(1), skills="")]
        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate(
            [{"guid": _guid(1)}], parsed_jobs
        )

        assert report.missing_field_rates["skills"] == 1.0

    def test_salary_is_not_one_of_the_missing_field_checks(self) -> None:
        # Structural check: We Work Remotely's feed has no salary field
        # at all, so unlike RemoteOK's validator this one must NOT report
        # a permanent, always-100% "salary" missing-rate -- see the
        # module docstring for why that would just be noise, not signal.
        report = WWRBatchValidator(settings=_LENIENT_SETTINGS).validate([], [])
        assert "salary" not in report.missing_field_rates

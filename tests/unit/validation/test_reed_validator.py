"""Unit tests for job_market_intel.validation.reed_validator.

Mirrors ``validation/test_remotive_validator.py``'s coverage and rationale
— see that module's docstring for why. This is a thin wrapper around the
shared ``validate_batch``, so these tests confirm Reed's own thresholds
and missing-field checks are wired correctly, not ``validate_batch``
itself (``validation/test_common.py``'s job).
"""

from __future__ import annotations

from job_market_intel.scrapers.reed.models import RawReedJob
from job_market_intel.validation.reed_validator import ReedBatchValidator, ReedValidationSettings

_LENIENT_SETTINGS = ReedValidationSettings(min_expected_jobs=1, max_skip_rate=0.50)


def _search(job_id: int) -> dict:
    return {"jobId": job_id, "jobTitle": "Engineer", "employerName": "Acme", "jobUrl": "https://x"}


def _parsed(job_id: int, **overrides: object) -> RawReedJob:
    search = _search(job_id)
    details = {
        "jobId": job_id,
        "currency": "GBP",
        "salaryType": "per annum",
        "fullTime": True,
    }
    details.update(overrides)
    return RawReedJob.from_combined(search, details)


class TestHealthyBatch:
    def test_healthy_batch_passes_with_no_issues(self) -> None:
        raw_jobs = [{"search": _search(i), "details": None} for i in range(25)]
        parsed_jobs = [_parsed(i) for i in range(25)]

        report = ReedBatchValidator(settings=ReedValidationSettings()).validate(
            raw_jobs, parsed_jobs
        )

        assert report.passed is True
        assert report.issues == []


class TestVolumeSanity:
    def test_too_few_parsed_jobs_is_flagged(self) -> None:
        settings = ReedValidationSettings(min_expected_jobs=20, max_skip_rate=0.50)
        raw_jobs = [{"search": _search(i), "details": None} for i in range(5)]
        parsed_jobs = [_parsed(i) for i in range(5)]

        report = ReedBatchValidator(settings=settings).validate(raw_jobs, parsed_jobs)

        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)


class TestMissingFieldChecks:
    def test_missing_employment_type_fields_are_reported(self) -> None:
        parsed_jobs = [
            _parsed(i, fullTime=None, partTime=None, contractType=None) for i in range(10)
        ]
        raw_jobs = [{"search": _search(i), "details": None} for i in range(10)]

        report = ReedBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.missing_field_rates.get("employment_type_raw") == 1.0

    def test_present_employment_type_is_not_reported_as_missing(self) -> None:
        parsed_jobs = [_parsed(i) for i in range(10)]  # fullTime=True on all
        raw_jobs = [{"search": _search(i), "details": None} for i in range(10)]

        report = ReedBatchValidator(settings=_LENIENT_SETTINGS).validate(raw_jobs, parsed_jobs)

        assert report.missing_field_rates.get("employment_type_raw", 0.0) == 0.0

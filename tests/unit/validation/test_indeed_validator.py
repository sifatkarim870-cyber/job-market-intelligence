"""Unit tests for job_market_intel.validation.indeed_validator.IndeedBatchValidator.

Thin-wrapper tests only — the shared arithmetic in validation/common.py's
validate_batch already has its own tests (test_common.py); these confirm
Indeed's own thresholds and missing-field checks are wired correctly.
"""

from __future__ import annotations

from job_market_intel.scrapers.indeed.models import RawIndeedJob
from job_market_intel.validation.indeed_validator import (
    IndeedBatchValidator,
    IndeedValidationSettings,
)


def _job(source_job_id: str, **overrides: object) -> RawIndeedJob:
    base = dict(
        source_job_id=source_job_id,
        job_title="Engineer",
        company_name="Acme",
        query_text="engineer",
        location_text="Remote",
        search_page_number=1,
    )
    base.update(overrides)
    return RawIndeedJob.model_validate(base)


class TestIndeedBatchValidator:
    def test_healthy_batch_passes(self) -> None:
        jobs = [_job(f"id{i}") for i in range(5)]
        report = IndeedBatchValidator().validate(
            raw_cards=[j.raw_payload for j in jobs], parsed_jobs=jobs
        )
        assert report.passed is True
        assert report.total_parsed == 5

    def test_below_min_expected_jobs_fails(self) -> None:
        settings = IndeedValidationSettings(min_expected_jobs=10)
        jobs = [_job("id1")]
        report = IndeedBatchValidator(settings=settings).validate(
            raw_cards=[j.raw_payload for j in jobs], parsed_jobs=jobs
        )
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_duplicate_source_job_ids_detected(self) -> None:
        jobs = [_job("dup"), _job("dup")]
        report = IndeedBatchValidator(
            settings=IndeedValidationSettings(min_expected_jobs=0)
        ).validate(raw_cards=[j.raw_payload for j in jobs], parsed_jobs=jobs)
        assert report.passed is False
        assert "dup" in report.duplicate_source_job_ids

    def test_missing_field_rates_report_description_and_detail_url(self) -> None:
        jobs = [_job("a", detail_url=None), _job("b", detail_url="https://x.test/1")]
        report = IndeedBatchValidator(
            settings=IndeedValidationSettings(min_expected_jobs=0)
        ).validate(raw_cards=[j.raw_payload for j in jobs], parsed_jobs=jobs)
        assert report.missing_field_rates["detail_url"] == 0.5
        assert report.missing_field_rates["description_raw"] == 1.0

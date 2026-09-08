"""Unit tests for job_market_intel.validation.common.validate_batch.

What these tests verify, and why each matters:
    - validate_batch works against plain dummy records that only happen
      to have a ``source_job_id`` attribute — never against
      ``RawRemoteOKJob`` or anything else RemoteOK-specific. This is the
      test suite proving ``validate_batch`` is genuinely source-agnostic
      (Step 14's whole point), not just RemoteOK's old logic renamed.
    - Every behavior ``RemoteOKBatchValidator``'s own test suite already
      covers (volume sanity, skip-rate sanity, duplicate detection,
      missing-field rates, zero-raw-records handling) holds at the
      generic-function level too, since that's now where the logic
      actually lives.
    - ``source_label`` is purely cosmetic: it changes issue-message text,
      never pass/fail outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_market_intel.validation.common import validate_batch


@dataclass
class DummyRecord:
    """A minimal stand-in for *any* future source's parsed-record type.

    Deliberately not RawRemoteOKJob, and not even a Pydantic model — the
    only thing validate_batch is allowed to depend on is a
    ``source_job_id`` attribute (see ``HasSourceJobId``).
    """

    source_job_id: str
    location: str | None = "Somewhere"
    salary: int | None = 100000
    description: str | None = "A description."
    extras: list[str] = field(default_factory=lambda: ["thing"])


_MISSING_FIELD_CHECKS = {
    "location": lambda r: r.location is None,
    "salary": lambda r: r.salary is None,
    "description": lambda r: not r.description,
    "extras": lambda r: len(r.extras) == 0,
}


def _records(n: int, **overrides: object) -> list[DummyRecord]:
    return [DummyRecord(source_job_id=str(i), **overrides) for i in range(n)]


class TestHealthyBatch:
    def test_healthy_batch_passes_with_no_issues(self) -> None:
        report = validate_batch(
            raw_records=[{"id": str(i)} for i in range(25)],
            parsed_records=_records(25),
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=20,
            max_skip_rate=0.10,
        )
        assert report.passed is True
        assert report.issues == []
        assert report.total_raw_records == 25
        assert report.total_parsed == 25
        assert report.skip_rate == 0.0
        assert report.duplicate_source_job_ids == []


class TestVolumeSanity:
    def test_too_few_parsed_records_is_flagged(self) -> None:
        report = validate_batch(
            raw_records=[{"id": str(i)} for i in range(5)],
            parsed_records=_records(5),
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=20,
            max_skip_rate=0.50,
        )
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_is_its_own_issue_and_never_divides_by_zero(self) -> None:
        report = validate_batch(
            raw_records=[],
            parsed_records=[],
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=1,
            max_skip_rate=0.50,
        )
        assert report.passed is False
        assert any("Zero raw records" in issue for issue in report.issues)
        assert report.skip_rate == 0.0

    def test_exactly_at_minimum_passes_the_volume_check(self) -> None:
        report = validate_batch(
            raw_records=[{"id": str(i)} for i in range(10)],
            parsed_records=_records(10),
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=10,
            max_skip_rate=0.50,
        )
        assert not any("below the configured minimum" in issue for issue in report.issues)


class TestSkipRateSanity:
    def test_high_skip_rate_is_flagged(self) -> None:
        report = validate_batch(
            raw_records=[{"id": str(i)} for i in range(10)],
            parsed_records=_records(5),
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=1,
            max_skip_rate=0.10,
        )
        assert report.passed is False
        assert report.skip_rate == 0.5
        assert any("Skip rate" in issue for issue in report.issues)

    def test_skip_rate_within_threshold_does_not_flag(self) -> None:
        report = validate_batch(
            raw_records=[{"id": str(i)} for i in range(10)],
            parsed_records=_records(9),
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=1,
            max_skip_rate=0.20,
        )
        assert not any("Skip rate" in issue for issue in report.issues)


class TestDuplicateDetection:
    def test_duplicate_source_job_ids_are_detected_and_named(self) -> None:
        parsed = [DummyRecord("1"), DummyRecord("2"), DummyRecord("1")]
        report = validate_batch(
            raw_records=[{"id": "1"}, {"id": "2"}, {"id": "1"}],
            parsed_records=parsed,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=1,
            max_skip_rate=0.50,
        )
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["1"]
        assert any("duplicate source_job_id" in issue for issue in report.issues)


class TestMissingFieldRates:
    def test_missing_field_rates_computed_correctly(self) -> None:
        parsed = [
            DummyRecord("1", location=None, salary=None),
            DummyRecord("2"),
        ]
        report = validate_batch(
            raw_records=[{"id": "1"}, {"id": "2"}],
            parsed_records=parsed,
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=1,
            max_skip_rate=0.50,
        )
        assert report.missing_field_rates["location"] == 0.5
        assert report.missing_field_rates["salary"] == 0.5
        assert report.missing_field_rates["description"] == 0.0
        assert report.missing_field_rates["extras"] == 0.0

    def test_missing_field_rates_are_zero_not_error_on_empty_batch(self) -> None:
        report = validate_batch(
            raw_records=[],
            parsed_records=[],
            missing_field_checks=_MISSING_FIELD_CHECKS,
            min_expected_records=1,
            max_skip_rate=0.50,
        )
        assert all(rate == 0.0 for rate in report.missing_field_rates.values())

    def test_custom_missing_field_checks_work_for_arbitrary_field_names(self) -> None:
        """A future source's validator can define entirely different
        field names/checks and validate_batch must honor them as-is —
        it has no hardcoded knowledge of any particular field."""
        checks = {"has_visa_flag": lambda r: not hasattr(r, "visa") or r.visa is None}

        @dataclass
        class VisaRecord:
            source_job_id: str
            visa: bool | None = None

        report = validate_batch(
            raw_records=[{"id": "1"}, {"id": "2"}],
            parsed_records=[VisaRecord("1", visa=True), VisaRecord("2", visa=None)],
            missing_field_checks=checks,
            min_expected_records=1,
            max_skip_rate=0.50,
        )
        assert report.missing_field_rates["has_visa_flag"] == 0.5


class TestSourceLabelIsCosmeticOnly:
    def test_source_label_changes_message_text_not_outcome(self) -> None:
        report_default = validate_batch(
            raw_records=[],
            parsed_records=[],
            missing_field_checks={},
            min_expected_records=1,
            max_skip_rate=0.50,
        )
        report_custom = validate_batch(
            raw_records=[],
            parsed_records=[],
            missing_field_checks={},
            min_expected_records=1,
            max_skip_rate=0.50,
            source_label="WeWorkRemotely",
        )
        assert report_default.passed is False
        assert report_custom.passed is False
        assert "the source" in report_default.issues[0]
        assert "WeWorkRemotely" in report_custom.issues[0]

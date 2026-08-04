"""Unit tests for job_market_intel.scrapers.remoteok.models.RawRemoteOKJob.

What these tests verify, and why each matters:
    - A complete, well-formed record validates correctly and every field
      maps from RemoteOK's raw naming to our model's naming as expected.
    - Fields RemoteOK frequently omits (salary, tags, company_logo,
      apply_url) are genuinely optional and default sensibly rather than
      raising.
    - Fields required for a record to be usable at all (id, position,
      company, url) actually enforce that requirement.
    - The custom date parser handles RemoteOK's ISO-8601 format, is
      resilient to malformed dates (returns None instead of raising), and
      always produces a timezone-aware datetime.
    - raw_payload preserves the original data even after normalization.
"""

from __future__ import annotations

from datetime import timezone

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob


class TestRequiredFields:
    """A job record missing any of these fields is unusable and must fail validation."""

    def test_valid_minimal_record_passes(self) -> None:
        job = RawRemoteOKJob.model_validate(
            {"id": "123", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        )
        assert job.source_job_id == "123"
        assert job.job_title == "Engineer"
        assert job.company_name == "Acme"
        assert job.original_url == "https://x.test/1"

    @pytest.mark.parametrize("missing_field", ["id", "position", "company", "url"])
    def test_missing_required_field_raises(self, missing_field: str) -> None:
        raw = {"id": "123", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        del raw[missing_field]
        with pytest.raises(ValidationError):
            RawRemoteOKJob.model_validate(raw)

    @pytest.mark.parametrize("empty_field", ["id", "position", "company", "url"])
    def test_empty_string_required_field_raises(self, empty_field: str) -> None:
        raw = {"id": "123", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        raw[empty_field] = ""
        with pytest.raises(ValidationError):
            RawRemoteOKJob.model_validate(raw)


class TestOptionalFields:
    """Fields RemoteOK frequently omits must default gracefully, never raise."""

    def _minimal(self, **overrides: object) -> dict:
        base = {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        base.update(overrides)
        return base

    def test_missing_tags_defaults_to_empty_list(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal())
        assert job.tags == []

    def test_null_tags_defaults_to_empty_list(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(tags=None))
        assert job.tags == []

    def test_tags_list_is_preserved(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(tags=["python", "remote"]))
        assert job.tags == ["python", "remote"]

    def test_missing_salary_defaults_to_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal())
        assert job.salary_min is None
        assert job.salary_max is None

    def test_negative_salary_raises(self) -> None:
        with pytest.raises(ValidationError):
            RawRemoteOKJob.model_validate(self._minimal(salary_min=-5000))

    def test_missing_location_defaults_to_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal())
        assert job.location_raw is None

    def test_missing_apply_url_defaults_to_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal())
        assert job.apply_url is None


class TestZeroSalaryNormalization:
    """RemoteOK sends a literal 0 (not null/omitted) when no salary was entered.

    Regression tests for a real bug caught in a live run: 0 passing an
    `is not None` check made every downstream consumer (batch validator,
    cleaner's completeness score) wrongly believe a salary was disclosed.
    """

    def _minimal(self, **overrides: object) -> dict:
        base = {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        base.update(overrides)
        return base

    def test_zero_salary_min_becomes_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(salary_min=0))
        assert job.salary_min is None

    def test_zero_salary_max_becomes_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(salary_max=0))
        assert job.salary_max is None

    def test_both_zero_both_become_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(salary_min=0, salary_max=0))
        assert job.salary_min is None
        assert job.salary_max is None

    def test_genuine_nonzero_salary_is_unaffected(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(salary_min=100000, salary_max=150000))
        assert job.salary_min == 100000
        assert job.salary_max == 150000

    def test_one_zero_one_real_value_only_the_zero_is_normalized(self) -> None:
        # salary_min unspecified (0), salary_max genuinely given.
        job = RawRemoteOKJob.model_validate(self._minimal(salary_min=0, salary_max=120000))
        assert job.salary_min is None
        assert job.salary_max == 120000


class TestPostingDateParsing:
    """The posting_date validator must handle RemoteOK's real format and degrade gracefully."""

    def _minimal(self, **overrides: object) -> dict:
        base = {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        base.update(overrides)
        return base

    def test_valid_iso8601_date_is_parsed(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(date="2026-01-15T09:00:00+00:00"))
        assert job.posting_date is not None
        assert job.posting_date.year == 2026
        assert job.posting_date.month == 1
        assert job.posting_date.day == 15

    def test_zulu_suffix_date_is_parsed(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(date="2026-01-15T09:00:00Z"))
        assert job.posting_date is not None
        assert job.posting_date.tzinfo is not None

    def test_naive_date_gets_utc_timezone_attached(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(date="2026-01-15T09:00:00"))
        assert job.posting_date is not None
        assert job.posting_date.tzinfo == timezone.utc

    def test_malformed_date_does_not_raise_and_becomes_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(date="not-a-real-date"))
        assert job.posting_date is None

    def test_missing_date_becomes_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal())
        assert job.posting_date is None

    def test_empty_string_date_becomes_none(self) -> None:
        job = RawRemoteOKJob.model_validate(self._minimal(date=""))
        assert job.posting_date is None


class TestRawPayloadPreservation:
    """The complete original record must be retained for auditability, per the design philosophy."""

    def test_raw_payload_is_stored_when_explicitly_provided(self) -> None:
        original = {
            "id": "1",
            "position": "Engineer",
            "company": "Acme",
            "url": "https://x.test/1",
            "some_future_field_we_dont_model_yet": "unexpected value",
        }
        job = RawRemoteOKJob.model_validate({**original, "raw_payload": original})
        assert job.raw_payload == original
        assert job.raw_payload["some_future_field_we_dont_model_yet"] == "unexpected value"

    def test_unmapped_fields_do_not_raise_due_to_extra_ignore(self) -> None:
        """A brand-new field RemoteOK adds tomorrow shouldn't break parsing today."""
        raw = {
            "id": "1",
            "position": "Engineer",
            "company": "Acme",
            "url": "https://x.test/1",
            "brand_new_field_remoteok_added_later": "surprise",
        }
        job = RawRemoteOKJob.model_validate(raw)
        assert job.source_job_id == "1"

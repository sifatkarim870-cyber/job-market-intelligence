"""Unit tests for job_market_intel.scrapers.remotive.models.RawRemotiveJob.

What these tests verify, and why each matters:
    - A complete, well-formed record validates correctly and every field
      maps from Remotive's raw naming to our model's naming as expected.
    - Fields required for a record to be usable at all (id, title,
      company_name, url) actually enforce that requirement.
    - ``_parse_salary_range``/the ``salary`` field validator extract a
      numeric range ONLY from the unambiguous "$X - $Y" shape, and
      deliberately leave everything else (single figures, "+", non-USD,
      free text, empty) as (None, None) — this is the one genuinely new
      piece of logic Remotive needed, and the conservative-scope decision
      it encodes matters enough to test exhaustively.
    - The ISO-8601 posting_date parser behaves the same way RemoteOK's
      does (same format, confirmed against official docs).
    - ``tags`` accepts either a list or a comma-separated string, per the
      live-shape uncertainty documented in models.py.
    - raw_payload preserves the original data even after normalization.
"""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.remotive.models import RawRemotiveJob, _parse_salary_range


class TestRequiredFields:
    """A job record missing any of these fields is unusable and must fail validation."""

    def test_valid_minimal_record_passes(self) -> None:
        job = RawRemotiveJob.model_validate(
            {"id": 123, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        )
        assert job.source_job_id == "123"
        assert job.job_title == "Engineer"
        assert job.company_name == "Acme"
        assert job.original_url == "https://x.test/1"

    @pytest.mark.parametrize("missing_field", ["id", "title", "company_name", "url"])
    def test_missing_required_field_raises(self, missing_field: str) -> None:
        raw = {"id": 123, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        del raw[missing_field]
        with pytest.raises(ValidationError):
            RawRemotiveJob.model_validate(raw)

    def test_empty_string_title_raises(self) -> None:
        raw = {"id": 123, "title": "", "company_name": "Acme", "url": "https://x.test/1"}
        with pytest.raises(ValidationError):
            RawRemotiveJob.model_validate(raw)

    def test_null_id_raises(self) -> None:
        raw = {"id": None, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        with pytest.raises(ValidationError):
            RawRemotiveJob.model_validate(raw)


class TestSourceJobIdCoercion:
    """Remotive's id is a genuine integer; source_job_id must be a str for every source."""

    def _minimal(self, **overrides: object) -> dict:
        base = {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        base.update(overrides)
        return base

    def test_integer_id_is_stringified(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(id=42))
        assert job.source_job_id == "42"
        assert isinstance(job.source_job_id, str)

    def test_string_id_is_preserved(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(id="42"))
        assert job.source_job_id == "42"


class TestOptionalFields:
    """Fields Remotive may omit must default gracefully, never raise."""

    def _minimal(self, **overrides: object) -> dict:
        base = {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        base.update(overrides)
        return base

    def test_missing_tags_defaults_to_empty_list(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal())
        assert job.tags == []

    def test_null_tags_defaults_to_empty_list(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(tags=None))
        assert job.tags == []

    def test_tags_list_is_preserved(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(tags=["python", "django"]))
        assert job.tags == ["python", "django"]

    def test_tags_as_comma_separated_string_is_split(self) -> None:
        # Defensive handling per the live-shape uncertainty documented in
        # models.py's module docstring.
        job = RawRemotiveJob.model_validate(self._minimal(tags="python, django"))
        assert job.tags == ["python", "django"]

    def test_missing_location_defaults_to_none(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal())
        assert job.location_raw is None

    def test_missing_company_logo_defaults_to_none(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal())
        assert job.company_logo_url is None

    def test_missing_category_and_job_type_default_to_none(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal())
        assert job.category_raw is None
        assert job.employment_type_raw is None


class TestSalaryRangeParsing:
    """The conservative "$X - $Y"-only salary parser: the one genuinely new piece of logic."""

    @pytest.mark.parametrize(
        ("raw_salary", "expected_min", "expected_max"),
        [
            ("$40,000 - $50,000", 40000, 50000),
            ("$40,000-$50,000", 40000, 50000),
            ("$40,000 – $50,000", 40000, 50000),  # en-dash, seen in the wild
            ("$40,000 to $50,000", 40000, 50000),
            ("$40k - $50k", 40000, 50000),
            ("$40K-$50K", 40000, 50000),
            ("$40,000 - 50,000", 40000, 50000),  # second $ omitted
        ],
    )
    def test_unambiguous_range_is_parsed(
        self, raw_salary: str, expected_min: int, expected_max: int
    ) -> None:
        assert _parse_salary_range(raw_salary) == (expected_min, expected_max)

    @pytest.mark.parametrize(
        "raw_salary",
        [
            None,
            "",
            "   ",
            "Competitive",
            "DOE",
            "$65,000",  # single figure, no range
            "$65,000+",  # "+"-suffixed floor
            "£40,000 - £55,000",  # non-USD symbol
            "40,000 - 50,000",  # no currency symbol at all
            "Up to $80,000",
        ],
    )
    def test_ambiguous_or_non_usd_text_is_left_unparsed(self, raw_salary: str | None) -> None:
        assert _parse_salary_range(raw_salary) == (None, None)

    @pytest.mark.parametrize(
        ("raw_salary", "expected_min", "expected_max"),
        [
            # Real production example: Remotive's free text wrote the
            # larger figure first. Positional-only parsing (the original
            # bug) returned (312000, 52000) here -- a min > max pair that
            # later failed core.jobs' ck_job_salaries_normalized_range
            # check constraint and, absent a per-job savepoint, took an
            # entire 18-job batch down with it. The parser must swap
            # rather than trust string order.
            ("$312,000 - $52,000", 52000, 312000),
            ("$50k - $40k", 40000, 50000),
        ],
    )
    def test_reversed_range_is_swapped_to_min_max_order(
        self, raw_salary: str, expected_min: int, expected_max: int
    ) -> None:
        assert _parse_salary_range(raw_salary) == (expected_min, expected_max)

    def test_field_is_populated_from_raw_salary_string(self) -> None:
        job = RawRemotiveJob.model_validate(
            {
                "id": 1,
                "title": "Engineer",
                "company_name": "Acme",
                "url": "https://x.test/1",
                "salary": "$100,000 - $150,000",
            }
        )
        assert job.salary_min == 100000
        assert job.salary_max == 150000

    def test_missing_salary_field_leaves_bounds_none(self) -> None:
        job = RawRemotiveJob.model_validate(
            {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        )
        assert job.salary_min is None
        assert job.salary_max is None

    def test_unparseable_salary_text_leaves_bounds_none(self) -> None:
        job = RawRemotiveJob.model_validate(
            {
                "id": 1,
                "title": "Engineer",
                "company_name": "Acme",
                "url": "https://x.test/1",
                "salary": "Competitive",
            }
        )
        assert job.salary_min is None
        assert job.salary_max is None

    def test_explicit_salary_min_max_win_over_parsing_raw_salary(self) -> None:
        # Mirrors RawWWRJob's "explicit values win" rule for direct
        # construction in tests.
        job = RawRemotiveJob.model_validate(
            {
                "id": 1,
                "title": "Engineer",
                "company_name": "Acme",
                "url": "https://x.test/1",
                "salary": "$1 - $2",
                "salary_min": 999,
                "salary_max": 1999,
            }
        )
        assert job.salary_min == 999
        assert job.salary_max == 1999


class TestPostingDateParsing:
    """The posting_date validator must handle Remotive's ISO-8601 format and degrade gracefully."""

    def _minimal(self, **overrides: object) -> dict:
        base = {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        base.update(overrides)
        return base

    def test_valid_iso8601_date_is_parsed(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(publication_date="2026-01-15T09:00:00"))
        assert job.posting_date is not None
        assert job.posting_date.year == 2026
        assert job.posting_date.month == 1
        assert job.posting_date.day == 15

    def test_naive_date_gets_utc_timezone_attached(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(publication_date="2026-01-15T09:00:00"))
        assert job.posting_date is not None
        assert job.posting_date.tzinfo == UTC

    def test_malformed_date_does_not_raise_and_becomes_none(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(publication_date="not-a-real-date"))
        assert job.posting_date is None

    def test_missing_date_becomes_none(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal())
        assert job.posting_date is None

    def test_empty_string_date_becomes_none(self) -> None:
        job = RawRemotiveJob.model_validate(self._minimal(publication_date=""))
        assert job.posting_date is None


class TestRawPayloadPreservation:
    """The complete original record must be retained for auditability, per the design philosophy."""

    def test_raw_payload_is_stored_when_explicitly_provided(self) -> None:
        original = {
            "id": 1,
            "title": "Engineer",
            "company_name": "Acme",
            "url": "https://x.test/1",
            "some_future_field_we_dont_model_yet": "unexpected value",
        }
        job = RawRemotiveJob.model_validate({**original, "raw_payload": original})
        assert job.raw_payload == original
        assert job.raw_payload["some_future_field_we_dont_model_yet"] == "unexpected value"

    def test_unmapped_fields_do_not_raise_due_to_extra_ignore(self) -> None:
        """A brand-new field Remotive adds tomorrow shouldn't break parsing today."""
        raw = {
            "id": 1,
            "title": "Engineer",
            "company_name": "Acme",
            "url": "https://x.test/1",
            "brand_new_field_remotive_added_later": "surprise",
        }
        job = RawRemotiveJob.model_validate(raw)
        assert job.source_job_id == "1"

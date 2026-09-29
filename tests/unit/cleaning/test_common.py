"""Unit tests for job_market_intel.cleaning.common.CleanedJob.

What these tests verify, and why each matters:
    - CleanedJob accepts a fully-populated record shaped like what
      RemoteOKCleaner (or any future source's cleaner) produces.
    - The skill/tag field is named ``skills``, not ``tags`` — this is the
      whole point of extracting a shared model (Step 14), so a regression
      here would silently reintroduce the per-source naming inconsistency
      this model exists to prevent.
    - CleanedJob has no required knowledge of RemoteOK or any other
      specific source: it can be constructed directly, without importing
      anything from ``scrapers.*``, proving it's genuinely source-agnostic
      rather than accidentally still coupled to one source's shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.common import CleanedJob

# The CleanedJob factory used below (`make_cleaned_job`) is the shared,
# root-level fixture in tests/conftest.py — see that file's module
# docstring for why it lives there instead of a local helper in this file.


class TestCleanedJobShape:
    def test_minimal_record_constructs_successfully(self, make_cleaned_job) -> None:
        job = make_cleaned_job()
        assert job.source_job_id == "1"
        assert job.skills == []

    def test_field_is_named_skills_not_tags(self, make_cleaned_job) -> None:
        """The entire point of Step 14's model rename: this field must be
        called ``skills`` to match the schema's ``ref.skills`` vocabulary,
        regardless of what any individual source calls it internally."""
        job = make_cleaned_job(skills=["python", "django"])
        assert job.skills == ["python", "django"]
        assert not hasattr(job, "tags")

    def test_fully_populated_record(self, make_cleaned_job) -> None:
        posting_date = datetime(2026, 1, 15, tzinfo=UTC)
        job = make_cleaned_job(
            company_logo_url="https://acme.test/logo.png",
            skills=["python", "sql"],
            location_cleaned="Remote - US",
            salary_min=100000,
            salary_max=150000,
            salary_disclosed=True,
            description_clean="We are hiring.",
            word_count=3,
            apply_url="https://acme.test/apply",
            posting_date=posting_date,
            data_quality_score=0.75,
            raw_payload={"id": "1"},
        )
        assert job.salary_min == 100000
        assert job.salary_max == 150000
        assert job.posting_date == posting_date
        assert job.raw_payload == {"id": "1"}

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            CleanedJob(job_title="Engineer")  # missing everything else

    def test_closing_date_defaults_to_none(self, make_cleaned_job) -> None:
        """closing_date is optional with a default so adding it didn't
        require touching every existing cleaner that has no such date to
        give (e.g. RemoteOKCleaner never sets it)."""
        job = make_cleaned_job()
        assert job.closing_date is None

    def test_closing_date_can_be_set_explicitly(self, make_cleaned_job) -> None:
        closing_date = datetime(2026, 9, 24, tzinfo=UTC)
        job = make_cleaned_job(closing_date=closing_date)
        assert job.closing_date == closing_date

    def test_currency_iso_code_and_pay_period_are_required(self) -> None:
        """Added for Reed: db.job_repository no longer supplies these as a
        hardcoded assumption, so every cleaner must state them explicitly
        -- a CleanedJob missing either must fail to construct, not
        silently fall back to something.
        """
        with pytest.raises(ValidationError):
            CleanedJob(
                source_job_id="1",
                job_title="Engineer",
                company_name="Acme",
                company_logo_url=None,
                skills=[],
                location_cleaned=None,
                salary_min=None,
                salary_max=None,
                salary_disclosed=False,
                description_clean=None,
                word_count=0,
                apply_url=None,
                original_url="https://x.test/1",
                posting_date=None,
                data_quality_score=0.0,
                raw_payload={},
                # currency_iso_code and pay_period deliberately omitted
            )

    def test_employment_type_code_defaults_to_none(self, make_cleaned_job) -> None:
        """Optional, unlike currency_iso_code/pay_period, since most
        sources (RemoteOK, Remotive, We Work Remotely) genuinely don't
        report an employment type at all -- None is an honest absence,
        not a guess. Reed is the first source to populate this."""
        job = make_cleaned_job()
        assert job.employment_type_code is None

    def test_employment_type_code_can_be_set_explicitly(self, make_cleaned_job) -> None:
        job = make_cleaned_job(employment_type_code="contract")
        assert job.employment_type_code == "contract"


class TestCleanedJobIsSourceAgnostic:
    def test_can_be_constructed_without_importing_any_scraper_package(self) -> None:
        """Regression guard: CleanedJob must never require knowledge of a
        specific source's raw model to build. If this starts requiring a
        RawXJob import (directly or transitively) to construct, the model
        has stopped being a shared contract and started being RemoteOK's
        model with a new name."""
        import sys

        scraper_modules_before = {
            name for name in sys.modules if name.startswith("job_market_intel.scrapers")
        }
        job = CleanedJob(
            source_job_id="future-source-1",
            job_title="Some Job",
            company_name="Some Co",
            company_logo_url=None,
            skills=["rust"],
            location_cleaned=None,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=None,
            word_count=0,
            apply_url=None,
            original_url="https://example.test/job/1",
            posting_date=None,
            data_quality_score=0.25,
            raw_payload={},
            currency_iso_code="USD",
            pay_period="yearly",
        )
        assert job.company_name == "Some Co"
        # Constructing a CleanedJob must not, as a side effect, have caused
        # any scraper package to be imported for the first time.
        scraper_modules_after = {
            name for name in sys.modules if name.startswith("job_market_intel.scrapers")
        }
        assert scraper_modules_after == scraper_modules_before

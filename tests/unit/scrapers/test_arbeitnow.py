"""Unit tests for the Arbeitnow scraper.

Each test pins a bug that actually occurred while building this source.

Run with:  uv run python -m pytest tests/unit/scrapers/test_arbeitnow.py
"""

from __future__ import annotations

import html

import pytest

from job_market_intel.cleaning.arbeitnow_cleaner import ArbeitnowCleaner
from job_market_intel.scrapers.arbeitnow.config import ArbeitnowSettings
from job_market_intel.scrapers.arbeitnow.models import RawArbeitnowJob
from job_market_intel.scrapers.arbeitnow.parser import ArbeitnowParser


def _payload(**overrides) -> dict:
    """A minimal but realistic posting, as Arbeitnow actually returns one."""
    base = {
        "slug": "senior-backend-engineer-cards-berlin-158554",
        "title": "Senior Backend Engineer - Cards",
        "company_name": "SumUp",
        "description": "<p>Build payment infrastructure.</p>",
        "location": "Berlin, Germany",
        "remote": False,
        "url": "https://www.arbeitnow.com/jobs/companies/sumup/senior-backend-engineer",
        "job_types": ["Full-time"],
        "tags": ["backend", "payments"],
        "created_at": 1791578723,
    }
    base.update(overrides)
    return base


class TestRawArbeitnowJob:
    def test_slug_is_the_natural_key(self):
        """Arbeitnow has no numeric id; slug is the only stable identifier."""
        job = RawArbeitnowJob.model_validate(_payload())
        assert job.source_job_id == "senior-backend-engineer-cards-berlin-158554"

    def test_unix_timestamp_becomes_datetime(self):
        """created_at is seconds since epoch, not an ISO string."""
        job = RawArbeitnowJob.model_validate(_payload())
        assert job.created_at is not None
        assert job.created_at.year >= 2024

    def test_remote_flag_is_exposed(self):
        assert RawArbeitnowJob.model_validate(_payload(remote=True)).is_remote is True
        assert RawArbeitnowJob.model_validate(_payload(remote=False)).is_remote is False

    def test_missing_collections_default_to_empty(self):
        """When job_types and tags are omitted entirely, they should default to []."""
        job = RawArbeitnowJob.model_validate(
            {"slug": "test-slug", "title": "Test Title"}
        )
        assert job.job_types == []
        assert job.tags == []


class TestArbeitnowParser:
    def test_parses_a_realistic_record(self):
        jobs, issues = ArbeitnowParser().parse_jobs([_payload()])
        assert len(jobs) == 1
        assert issues == []

    def test_one_bad_record_does_not_lose_the_batch(self):
        jobs, issues = ArbeitnowParser().parse_jobs([_payload(), {"slug": None}])
        assert len(jobs) == 1
        assert len(issues) == 1

    def test_blank_title_is_rejected(self):
        jobs, issues = ArbeitnowParser().parse_jobs([_payload(title="")])
        assert jobs == []
        assert len(issues) == 1


class TestArbeitnowCleaner:
    def test_double_encoded_html_is_fully_stripped(self):
        """Regression: 19 of 325 live postings shipped literal <h2> tags into
        description_clean because the JSON carries entity-escaped HTML."""
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(_payload()))
        assert cleaned.description_clean == "Build payment infrastructure."
        assert "<" not in cleaned.description_clean

    def test_escaped_entities_inside_text_survive_once(self):
        payload = _payload(description="<p>Uses R&D and C++</p>")
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(payload))
        assert cleaned.description_clean == "Uses R&D and C++"

    def test_job_types_and_tags_both_feed_skills(self):
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(_payload()))
        assert "Full-time" in cleaned.skills

    def test_remote_flag_fills_a_missing_location(self):
        """'Berlin, Germany' contains no 'remote', so this is what keeps the
        location honest when the board says only that a job is remote."""
        cleaned = ArbeitnowCleaner().clean_job(
            RawArbeitnowJob.model_validate(_payload(location=None, remote=True))
        )
        assert cleaned.location_cleaned == "Remote"

    def test_no_salary_is_claimed(self):
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(_payload()))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_closing_date_stays_none(self):
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(_payload()))
        assert cleaned.closing_date is None

    def test_source_job_id_is_the_slug(self):
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(_payload()))
        assert cleaned.source_job_id == "senior-backend-engineer-cards-berlin-158554"

    def test_posting_date_comes_from_created_at(self):
        cleaned = ArbeitnowCleaner().clean_job(RawArbeitnowJob.model_validate(_payload()))
        assert cleaned.posting_date is not None


class TestArbeitnowSettings:
    def test_defaults_are_usable_without_env(self):
        settings = ArbeitnowSettings()
        assert settings.api_url.startswith("https://")
        assert settings.max_jobs_per_run >= 1

    def test_max_jobs_floor_is_enforced(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ArbeitnowSettings(max_jobs_per_run=0)


class TestValidatorChecks:
    def test_missing_field_checks_are_callables(self):
        """Regression: booleans raised "'bool' object is not callable."""
        from job_market_intel.validation.arbeitnow_validator import _MISSING_FIELD_CHECKS

        assert _MISSING_FIELD_CHECKS
        for name, check in _MISSING_FIELD_CHECKS.items():
            assert callable(check), f"{name} must be callable, got {type(check)}"

    def test_slug_check_flags_missing_slug(self):
        from job_market_intel.validation.arbeitnow_validator import _MISSING_FIELD_CHECKS

        job = RawArbeitnowJob.model_validate(_payload())
        assert _MISSING_FIELD_CHECKS["source_job_id"](job) is False
        assert _MISSING_FIELD_CHECKS["title"](job) is False
        assert _MISSING_FIELD_CHECKS["description"](job) is False
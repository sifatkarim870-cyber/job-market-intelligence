"""Unit tests for job_market_intel.scrapers.indeed.models.RawIndeedJob.

What these tests verify, and why each matters:
    - A complete, well-formed record validates correctly.
    - job_title/company_name are genuinely required (an Indeed card
      without either is unusable).
    - Optional text fields normalize "N/A"/"—"/empty-after-whitespace-
      collapse into None rather than storing placeholder text as if it
      were real data.
    - benefits gets cleaned and empty entries dropped.
    - raw_payload survives untouched — the "never discard original source
      data" guarantee every other source's raw model already has.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.indeed.models import RawIndeedJob


def _minimal(**overrides: object) -> dict:
    base = {
        "source_job_id": "abc123",
        "job_title": "Software Engineer",
        "company_name": "Acme Corp",
        "query_text": "software engineer",
        "location_text": "Remote",
        "search_page_number": 1,
    }
    base.update(overrides)
    return base


class TestRequiredFields:
    def test_valid_minimal_record_passes(self) -> None:
        job = RawIndeedJob.model_validate(_minimal())
        assert job.source_job_id == "abc123"
        assert job.job_title == "Software Engineer"
        assert job.company_name == "Acme Corp"
        assert job.benefits == []
        assert job.is_sponsored is False

    @pytest.mark.parametrize("missing_field", ["job_title", "company_name", "source_job_id"])
    def test_missing_required_field_raises(self, missing_field: str) -> None:
        raw = _minimal()
        del raw[missing_field]
        with pytest.raises(ValidationError):
            RawIndeedJob.model_validate(raw)


class TestOptionalTextNormalization:
    @pytest.mark.parametrize("placeholder", ["N/A", "—", "-", "", "   "])
    def test_placeholder_salary_text_becomes_none(self, placeholder: str) -> None:
        job = RawIndeedJob.model_validate(_minimal(salary_text=placeholder))
        assert job.salary_text is None

    def test_real_salary_text_is_preserved_and_whitespace_collapsed(self) -> None:
        job = RawIndeedJob.model_validate(_minimal(salary_text="$70,000  -   $90,000  a  year"))
        assert job.salary_text == "$70,000 - $90,000 a year"

    def test_location_raw_whitespace_collapsed(self) -> None:
        job = RawIndeedJob.model_validate(_minimal(location_raw="  Austin,   TX  "))
        assert job.location_raw == "Austin, TX"

    def test_description_raw_none_by_default(self) -> None:
        job = RawIndeedJob.model_validate(_minimal())
        assert job.description_raw is None


class TestBenefits:
    def test_benefits_cleaned_and_empty_entries_dropped(self) -> None:
        job = RawIndeedJob.model_validate(
            _minimal(benefits=["  Health insurance ", "", "401(k)", "N/A"])
        )
        assert job.benefits == ["Health insurance", "401(k)"]


class TestRawPayload:
    def test_raw_payload_defaults_empty(self) -> None:
        job = RawIndeedJob.model_validate(_minimal())
        assert job.raw_payload == {}

    def test_raw_payload_preserves_original_values(self) -> None:
        payload = {"job_title": "Software Engineer", "is_sponsored": True}
        job = RawIndeedJob.model_validate(_minimal(raw_payload=payload))
        assert job.raw_payload == payload

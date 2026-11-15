"""Pydantic data models for Jobkorea scraper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RawJobkoreaJob(BaseModel):
    """Raw Jobkorea job posting before parsing."""

    url: str
    job_id: str
    html_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CleanedJobkoreaJob(BaseModel):
    """Cleaned Jobkorea job posting ready for ingestion into core.jobs."""

    source_code: str = "jobkorea_kr"
    source_job_id: str
    job_title: str
    company_name: str
    location_cleaned: str
    country_iso_code: str = "KR"
    raw_description: str
    description_sections: dict[str, Any] = Field(default_factory=dict)
    employment_type_code: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency_iso_code: str | None = None
    pay_period: str | None = None
    salary_disclosed: bool = False
    skills: list[str] = Field(default_factory=list)
    closing_date: str | None = None
    posting_date: str | None = None
    word_count: int = 0

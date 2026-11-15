"""Data models for GoodWork (Canada) postings."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class RawGoodworkJob(BaseModel):
    """Raw data extracted from a GoodWork job detail page."""

    url: str = Field(..., description="Absolute URL of the job posting")
    job_id: str = Field(..., description="Unique job posting ID")
    html_content: str = Field(..., description="Raw HTML of the page or main section")
    title: str | None = Field(default=None, description="Job title")
    company: str | None = Field(default=None, description="Hiring organization")
    location: str | None = Field(default=None, description="Job location")
    date_posted: str | None = Field(default=None, description="Posting date string")
    closing_date: str | None = Field(default=None, description="Closing date string if present")

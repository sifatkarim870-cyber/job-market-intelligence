"""Data models for Job.com.bd postings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RawJobComBdJob(BaseModel):
    """Raw data extracted from a Job.com.bd detail page."""

    url: str = Field(..., description="Absolute URL to the job vacancy")
    job_id: str = Field(..., description="Unique job identifier")
    html_content: str = Field(..., description="Raw HTML of the detail page")

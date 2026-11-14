"""Data models for JobBKK (Thailand) postings."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class RawJobbkkJob(BaseModel):
    """Raw JobPosting data extracted from JobBKK JSON-LD."""

    url: str = Field(..., description="Absolute canonical URL of the job detail page")
    emp_id: str = Field(..., description="Employer ID extracted from URL path")
    job_id: str = Field(..., description="Job vacancy ID extracted from URL path")
    json_ld: dict[str, Any] = Field(default_factory=dict, description="Schema.org JobPosting dictionary")
    html_title: str | None = Field(default=None, description="HTML title tag if parsed")

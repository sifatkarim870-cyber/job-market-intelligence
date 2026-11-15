"""Data models for WorkInNonProfits (Canada) postings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscoveredJobItem(BaseModel):
    """Metadata item discovered from the WorkInNonProfits RSS / Atom feed."""

    url: str = Field(..., description="Absolute URL to the job posting")
    job_id: str = Field(..., description="Unique vacancy identifier")
    title: str = Field(..., description="Job title")
    employer: str | None = Field(default=None, description="Hiring organization")
    location: str | None = Field(default=None, description="Location text from feed")
    type_info: str | None = Field(default=None, description="Employment type and salary hint")
    deadline: str | None = Field(default=None, description="Application deadline string")
    pub_date: str | None = Field(default=None, description="Publication date string")


class RawWorkInNonProfitsJob(BaseModel):
    """Raw record containing feed metadata and detail page HTML."""

    item: DiscoveredJobItem = Field(..., description="Feed metadata")
    html_content: str = Field(..., description="Raw HTML of the detail page")

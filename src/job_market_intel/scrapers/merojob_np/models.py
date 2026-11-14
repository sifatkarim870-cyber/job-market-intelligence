"""Data models for raw Merojob (Nepal) postings."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class RawMerojobListingItem(BaseModel):
    """Pydantic model representing a single raw item from Merojob jobs listing API."""

    id: int = Field(..., description="Unique vacancy identifier")
    title: str = Field(..., description="Job title")
    slug: str = Field(..., description="URL slug for the vacancy")
    absolute_url: str | None = Field(default=None, description="Relative or absolute URL path")
    client: dict[str, Any] | None = Field(default=None, description="Client/employer dictionary")
    skills: list[str] = Field(default_factory=list, description="Extracted skills")
    job_locations: list[dict[str, Any]] = Field(default_factory=list, description="Location records")
    offered_salary: dict[str, Any] | None = Field(default=None, description="Salary details")
    job_level: str | None = Field(default=None, description="Level e.g. Mid Level, Entry Level")
    available_for: list[str] = Field(default_factory=list, description="Employment type e.g. Full Time")
    education_level: str | None = Field(default=None, description="Required education level")
    experience_required: str | None = Field(default=None, description="Required experience")
    deadline: str | None = Field(default=None, description="Closing deadline ISO string")
    posted_at: str | None = Field(default=None, description="Posting datetime ISO string")
    posted_date: str | None = Field(default=None, description="Posting date string")


class RawMerojobJob(BaseModel):
    """Merged model containing both listing summary and full vacancy details."""

    id: int
    title: str
    slug: str
    absolute_url: str | None = None
    client: dict[str, Any] | None = None
    description: str | None = None
    specification: str | None = None
    extra_description: str | None = None
    alternate_description: str | None = None
    skills: list[str] = Field(default_factory=list)
    job_locations: list[dict[str, Any]] = Field(default_factory=list)
    offered_salary: dict[str, Any] | None = None
    job_level: str | None = None
    available_for: list[str] = Field(default_factory=list)
    education_level: str | None = None
    experience_required: str | None = None
    deadline: str | None = None
    posted_at: str | None = None
    posted_date: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

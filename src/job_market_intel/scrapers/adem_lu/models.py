"""Data models for raw ADEM job payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RawAdemLuJob(BaseModel):
    """Raw job item returned by ADEM's jobboard API."""

    ref: str = Field(..., description="Job reference ID")
    title: str = Field(..., description="Job title")
    employer: str | None = Field(default=None, description="Hiring company")
    commune: str | None = Field(default=None)
    canton: str | None = Field(default=None)
    domain: str | None = Field(default=None)
    job: str | None = Field(default=None)
    contract: str | None = Field(default=None)
    duration: str | None = Field(default=None)
    time: str | None = Field(default=None)
    hours: float | None = Field(default=None)
    experience: str | None = Field(default=None)
    languages: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    description_text: str | None = Field(default=None)
    apply_url: str | None = Field(default=None)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

"""Data models for the VDAB (vdab.be) scraper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawVdabJob(BaseModel):
    """Raw search-listing row and detail payload for one VDAB vacancy.

    ``listing`` is the row the search endpoint returned (a discovery hint only).
    ``payload`` is the full detail JSON for the ad. The canonical id lives in
    ``job_id`` and is taken from the ad itself, never from a URL slug.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    listing: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class VdabPipelineRunResult(BaseModel):
    """Execution summary for a VDAB scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    cleaned_count: int = Field(default=0)
    pages_scraped: int = Field(default=0)
    discovered_count: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)

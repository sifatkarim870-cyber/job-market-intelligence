"""Data models for the Vinnumalastofnun (Iceland) scraper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawVinnumalastofnunIsJob(BaseModel):
    """One generic-list item plus the detail document fetched for it.

    The list item already carries the title (which embeds the employer), the
    application deadline and the region/ratio tags, so a failed detail request
    still leaves a usable record: ``detail`` is ``None`` and the parser falls
    back to the item's short card intro. The detail carries the full
    description, which is the reason a run fetches it, but its absence is not
    fatal.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    slug: str
    url: str
    list_position: int
    list_total: int
    list_item: dict[str, Any]
    detail: dict[str, Any] | None = None


class VinnumalastofnunIsPipelineRunResult(BaseModel):
    """Execution summary for a Vinnumalastofnun scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    cleaned_count: int = Field(default=0)
    total_results: int = Field(default=0)
    pages_scanned: int = Field(default=0)
    pages_fetched: int = Field(default=0)
    fetch_failures: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)

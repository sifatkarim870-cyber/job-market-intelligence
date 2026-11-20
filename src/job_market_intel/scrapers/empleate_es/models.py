"""Data models for the Empléate (Spain) scraper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawEmpleateEsJob(BaseModel):
    """One Solr search document plus the page it was read from.

    Empléate's public search endpoint returns the *whole* posting in the
    listing response, including the full ``contenido`` description, employer,
    province, contract type and salary bounds. There is therefore no detail
    request per job: one page of 100 costs one HTTP request.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    search_page_start: int
    document: dict[str, Any]


class EmpleateEsPipelineRunResult(BaseModel):
    """Execution summary for an Empléate scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    cleaned_count: int = Field(default=0)
    pages_scraped: int = Field(default=0)
    total_available: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)

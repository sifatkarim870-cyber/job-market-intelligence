"""Data models for the Emploi.cm (emploi.cm) scraper."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RawEmploiCmJob(BaseModel):
    """Raw HTML payload and metadata for a single Emploi.cm vacancy."""

    model_config = ConfigDict(frozen=True)

    url: str
    job_id: str
    html_content: str


class EmploiCmPipelineRunResult(BaseModel):
    """Execution summary for an Emploi.cm scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    cleaned_count: int = Field(default=0)
    pages_scraped: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)

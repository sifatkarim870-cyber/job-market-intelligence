"""Data models for the Emploi.cd (DR Congo) scraper."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RawEmploiCdJob(BaseModel):
    """Raw HTML payload and metadata for a single Emploi.cd vacancy."""

    model_config = ConfigDict(frozen=True)

    url: str
    job_id: str
    html_content: str


class EmploiCdPipelineRunResult(BaseModel):
    """Execution summary for an Emploi.cd scraper run."""

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

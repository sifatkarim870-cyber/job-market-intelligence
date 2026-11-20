"""Data models for the Emploi Bénin (emploibenin.com) scraper."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RawEmploiBeninJob(BaseModel):
    """Raw HTML payload and metadata for a single Emploi Bénin vacancy."""

    model_config = ConfigDict(frozen=True)

    url: str
    job_id: str
    html_content: str


class EmploiBeninPipelineRunResult(BaseModel):
    """Execution summary for an Emploi Bénin scraper run."""

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

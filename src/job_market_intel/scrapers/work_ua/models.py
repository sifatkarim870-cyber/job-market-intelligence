"""Data models for the work.ua (Ukraine) scraper."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RawWorkUaJob(BaseModel):
    """One listing card plus the ad page fetched for it.

    The listing card already carries the title, so a failed ad fetch still
    leaves a usable (if thin) record: ``detail_html`` is ``None`` and the
    parser falls back to the listing title with no description. The ad page
    carries the employer, salary, address, schedule, body and activation
    timestamp, so a run is far richer with it.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    list_position: int
    listing_title: str
    list_total: int | None = None
    detail_html: str | None = None


class WorkUaPipelineRunResult(BaseModel):
    """Execution summary for a work.ua scraper run."""

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

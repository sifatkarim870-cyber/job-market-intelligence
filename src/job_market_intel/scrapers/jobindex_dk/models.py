"""Data models for the Jobindex (jobindex.dk) scraper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobIndexJob(BaseModel):
    """Raw payload and metadata for a single Jobindex ad.

    ``listing`` is the board's own ``results[]`` object for this ``tid`` (title,
    company, dates, area, addresses, salary, ``home_workplace`` and the rendered
    snippet). ``html_content`` is whichever page was fetched: the canonical
    ``/jobannonce/<tid>/<slug>`` page when one exists (``page_kind ==
    "jobannonce"``, full body), otherwise the ``/vis-job/<tid>`` teaser page
    (``page_kind == "vis_job"``).
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    listing: dict[str, Any]
    ad_url: str
    html_content: str
    page_kind: str


class JobIndexPipelineRunResult(BaseModel):
    """Execution summary for a Jobindex scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    cleaned_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    pages_scraped: int = Field(default=0)
    discovered_count: int = Field(default=0)
    fetch_failures: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)

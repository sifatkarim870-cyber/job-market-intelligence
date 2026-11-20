"""Data models for the jobup.ch scraper."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SitemapEntry(BaseModel):
    """One ``<url>`` entry from jobup.ch's advertised job sitemap.

    ``position`` is the entry's index in document order after the client has
    sorted by ``lastmod`` (newest first). The sitemap is written oldest-first,
    so the sort is what makes ``fresh_rows`` mean "the newest postings".
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    lastmod: str | None = None
    position: int = 0


class RawJobupChJob(BaseModel):
    """One sitemap entry plus the ad page fetched for it.

    ``html_content`` is ``None`` when the detail request failed; the client
    records that failure separately and the parser skips the entry. The
    sitemap carries only URLs and ``lastmod`` values, so there is no
    listing-side fallback.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    sitemap_position: int
    sitemap_total: int
    lastmod: str | None = None
    html_content: str | None = None


class JobupChPipelineRunResult(BaseModel):
    """Execution summary for a jobup.ch scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    cleaned_count: int = Field(default=0)
    sitemap_entries: int = Field(default=0)
    pages_fetched: int = Field(default=0)
    fetch_failures: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)

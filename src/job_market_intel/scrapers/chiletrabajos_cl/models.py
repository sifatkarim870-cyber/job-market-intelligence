"""Data models for the Chiletrabajos (chiletrabajos.cl) scraper."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SitemapEntry(BaseModel):
    """One ``<url>`` entry from the board's advertised sitemap.

    ``position`` is the entry's zero-based index in document order. The
    sitemap is generated newest-first, so a smaller position is a fresher
    posting and the position is also the key the rotating archive window
    uses.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    lastmod: str | None = None
    position: int = 0


class RawChiletrabajosJob(BaseModel):
    """One sitemap entry plus the ad page fetched for it.

    ``html_content`` is ``None`` when the detail request failed; the client
    records that failure separately and the parser skips the entry. There is
    no listing-side title/employer to fall back on because this board's
    sitemap carries only URLs and ``lastmod`` values.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    sitemap_position: int
    sitemap_total: int
    lastmod: str | None = None
    html_content: str | None = None


class ChiletrabajosClPipelineRunResult(BaseModel):
    """Execution summary for a Chiletrabajos scraper run."""

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

"""The raw record an HTML-scraped posting is parsed into."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawHtmlScraperJob(BaseModel):
    """One posting scraped via the generic HTML scraper framework."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_job_id: str = Field(..., description="Source-specific job identifier.")
    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    description: str | None = Field(default=None)
    location: str | None = Field(default=None)
    country: str | None = Field(default=None)
    employment_type: str | None = Field(default=None)
    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)
    url: str | None = Field(default=None, description="Canonical detail URL.")
    listing_page: int | None = Field(default=None)
    raw: dict[str, Any] = Field(default_factory=dict, description="Unmodified payload.")

    def posted_datetime(self) -> datetime | None:
        if self.posted_date is None:
            return None
        return datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)

    def closing_datetime(self) -> datetime | None:
        if self.closing_date is None:
            return None
        return datetime(self.closing_date.year, self.closing_date.month, self.closing_date.day)

"""The raw record a Hiiraan posting is parsed into.

Hiiraan publishes postings as **PDF** Terms of Reference rather than HTML.
Measured 2026-10-18 across four PDFs, each carries labelled fields::

    Position Title: Full-Stack Software Engineer
    Department: Information Technology
    Position Level: Level 1 Officer
    Reports To: Head of Information Technology
    Employment Type: Full-time
    Location: Mogadishu, Somalia
    Deadline for submission: 17th August 2026, 11.59 PM Mogadishu time.

* **No salary, no posting date, no company field.** The employer is the
  organization named in the background prose, which is not a field, so
  ``company_name`` stays "Unknown employer".
* **No identifier**, so the URL slug (the PDF filename) is the key.
* Text is extracted with ``pypdf`` (a declared dependency, not an ad-hoc
  install).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawHiiraanJobsJob(BaseModel):
    """One Hiiraan posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The PDF filename stem, e.g. "1785793050_full-stacksoftwareengineer-tor".
    source_job_id: str = Field(..., description="Hiiraan posting slug (PDF filename).")

    title: str = Field(..., description="Job title, from 'Position Title:'.")
    company_name: str = Field(default="Unknown employer")

    department: str | None = Field(default=None)
    position_level: str | None = Field(default=None)
    reports_to: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
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

"""The raw record a CareerJunction posting is parsed into.

CareerJunction publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page. Measured over 1
posting on 2026-10-17, the payload carries:

    title, url, datePosted, validThrough, description, industry,
    employmentType, baseSalary, hiringOrganization (name + url),
    jobLocation (address with locality + country, geo)

Two things are absent and are facts about the board rather than parser gaps:

* **No ``identifier``**. The stable key is the numeric id from the URL.
* **No real ``baseSalary``**. The value is ``"R Undisclosed"``, which is not a
  salary. Every salary field stays ``None`` and ``salary_disclosed`` is always
  ``False``.

The JSON-LD is **malformed**: the ``description`` string contains raw newlines
and HTML entities, which makes ``json.loads`` raise ``Invalid control
character``. The parser uses ``json.loads(block, strict=False)``, which tolerates
control characters inside strings.

``datePosted`` / ``validThrough`` are formatted ``"2026/10/16 10:33:33 AM"`` --
not ISO 8601. A custom date parser handles this.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawCareerJunctionJob(BaseModel):
    """One CareerJunction posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The posting id, e.g. "2646292". The URL is authoritative, so it is what
    #: makes re-runs idempotent.
    source_job_id: str = Field(..., description="CareerJunction posting id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_url: str | None = Field(default=None)
    industry: str | None = Field(default=None, description="e.g. 'admin, office & support'.")
    employment_type: str | None = Field(default=None, description="e.g. 'Default'.")

    location: str | None = Field(default=None, description="'City' from jobLocation.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'ZA'.")
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)

    description: str | None = Field(default=None, description="HTML from the JSON-LD.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None, description="Which listing page found it.")

    raw: dict[str, Any] = Field(default_factory=dict, description="Unmodified payload.")

    def posted_datetime(self) -> datetime | None:
        """posting_date as a datetime, or None."""
        if self.posted_date is None:
            return None
        return datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)

    def closing_datetime(self) -> datetime | None:
        """closing_date as a datetime, or None."""
        if self.closing_date is None:
            return None
        return datetime(self.closing_date.year, self.closing_date.month, self.closing_date.day)

"""The raw record a Net-Empregos posting is parsed into.

Net-Empregos publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page. Measured over 3
postings on 2026-10-16, the payload carries:

    title, description, datePosted, validThrough, employmentType,
    hiringOrganization (name + logo), jobLocation (address with locality,
    region, country, postalCode, streetAddress), industry

Two things are absent and are facts about the board rather than parser gaps:

* **No ``identifier``**. The stable key is the numeric id from the URL.
* **No ``baseSalary``**. Net-Empregos publishes no salary in its structured
  data, so every salary field stays ``None`` and ``salary_disclosed`` is always
  ``False``.

The JSON-LD is **malformed**: the ``description`` string contains raw newlines,
which makes ``json.loads`` raise ``Invalid control character``. The parser uses
``json.loads(block, strict=False)``, which tolerates control characters inside
strings. Every field extracts cleanly that way.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawNetEmpregosJob(BaseModel):
    """One Net-Empregos posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The posting id, e.g. "16131249". The URL is authoritative, so it is what
    #: makes re-runs idempotent.
    source_job_id: str = Field(..., description="Net-Empregos posting id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None, description="A plain URL string.")
    industry: str | None = Field(default=None, description="e.g. 'Call Center / Help Desk'.")
    employment_type: str | None = Field(default=None, description="e.g. FULL_TIME.")

    location: str | None = Field(default=None, description="'City, Region' from jobLocation.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'PT'.")
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)
    postal_code: str | None = Field(default=None)
    street_address: str | None = Field(default=None)

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

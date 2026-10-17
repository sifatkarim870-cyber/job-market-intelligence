"""The raw record a Jobs.af posting is parsed into.

Jobs.af publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page. Measured on 2026-10-18,
the payload carries::

    @context, @type, title, description, datePosted, validThrough,
    employmentType, hiringOrganization (name + logo), jobLocation, directApply

Traps, each measured:

* ``addressCountry`` is the **name** ``"Afghanistan"``, not the ISO code
  ``"AF"``. The same shape as Vagas.com.br's ``"Brasil"``; an unmapped name
  resolves to no country and the row collapses onto global-remote.
* ``datePosted`` carries **milliseconds and a truncated offset** --
  ``"2026-10-17 10:48:27.175+00"``. ``+00`` has no minutes, so this is not ISO
  8601 and a strict parser returns nothing for every posting. ``validThrough`` is
  ``"2026-10-30 00:00:00+00"``, the same shape without milliseconds.
* **No ``identifier``**, so the URL slug is the key -- which is also what makes
  re-runs idempotent.
* **No ``baseSalary``** on the measured posting, so no salary is stored.

``directApply`` is ``true``, which is recorded in ``raw`` rather than mapped:
the corpus has no column for it and inventing one is a schema change, not a
scraping decision.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobsAfJob(BaseModel):
    """One Jobs.af posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "assistant-branch-manager-31". The board publishes no
    #: ``identifier``, so this is the only stable key.
    source_job_id: str = Field(..., description="Jobs.af posting slug.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None)
    employment_type: str | None = Field(default=None)
    industry: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default=None, description="addressCountry, e.g. 'Afghanistan'.")

    description: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None)

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

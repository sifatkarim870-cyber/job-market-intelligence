"""The raw record an Angola Emprego posting is parsed into.

Angola Emprego publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page. Measured over 2
postings on 2026-10-18, the payload carries::

    @context, @type, title, description, datePosted, validThrough,
    employmentType, hiringOrganization (name + logo), identifier,
    jobLocation (address: locality, region, country)

Traps, each measured:

* ``employmentType`` is a **list** (``["FULL_TIME"]``), not the bare string
  every other source here uses. ``value.strip()`` raises ``AttributeError``
  and takes the whole batch with it.
* ``identifier`` is ``{"@type": "PropertyValue", "value": "<slug string>"}`` --
  a slug, not an int and not the numeric URL suffix. Some URL slugs end
  ``-4818`` and others do not, so the URL slug is the only reliable key.
* **No ``baseSalary``** on any measured posting, so salary coverage is zero by
  nature of the board rather than by parser failure.

``datePosted``/``validThrough`` are full ISO timestamps with a timezone offset
("2026-10-17T08:30:47+00:00").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawAngolaEmpregoJob(BaseModel):
    """One Angola Emprego posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "grande-oportunidade-para-coordenador-industrial-4818".
    #: The slug is the key because ``identifier.value`` is a different string
    #: and the numeric suffix is not always present.
    source_job_id: str = Field(..., description="Angola Emprego posting slug.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None)
    industry: str | None = Field(default=None)
    #: Always a **list** on this board, e.g. ``["FULL_TIME"]``.
    employment_type: list[str] | None = Field(default=None)

    location: str | None = Field(default=None, description="'City, Region'.")
    country: str | None = Field(default=None)
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)

    description: str | None = Field(default=None)

    salary_currency: str | None = Field(default=None)
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)

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

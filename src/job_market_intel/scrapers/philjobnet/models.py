"""The raw record a PhilJobNet posting is parsed into.

PhilJobNet publishes **no structured data** -- no schema.org JSON-LD. Everything
is markup extraction from a ``.portfolio-details`` block.

Measured 2026-10-18 across three detail pages. The block renders as::

    BUILDING ADMINISTRATOR
    Salary not specified
    1PRIME RETAIL CORPORATION
    Apply now
    DUMAGUETE CITY (CAPITAL), NEGROS ORIENTAL
    COLLEGE GRADUATE
    Permanent
    Job Description
    Posted on 17 October 2026
    <description>

or, when a salary is stated::

    BUSINESS DEVELOPMENT OFFICER
    ₱20,000.00
    I PROCESS LIAISON AND CONSULTANCY OPC
    Apply now
    BACUNGAN (LEON T. POSTIGO), ZAMBOANGA DEL NORTE
    ELEMENTARY GRADUATE
    Project-based
    Job Description
    Posted on 17 October 2026
    <description>

* ``Salary`` reads ``"not specified"`` on most postings and a single figure
  (``\"₱20,000.00\"``) on some. The figure has no stated period.
* ``og:title`` / ``og:description`` are **site-wide** (\"PhilJobNet | Job Details\")
  and must not be used.
* No ``identifier``, no ``baseSalary`` JSON-LD, no country field.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawPhilJobNetJob(BaseModel):
    """One PhilJobNet posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from the slug, e.g. "building-administrator-1490669".
    source_job_id: str = Field(..., description="PhilJobNet posting slug.")

    title: str = Field(..., description="Job title, from <h1>.")
    company_name: str = Field(default="Unknown employer")

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)
    education_level: str | None = Field(default=None)

    salary_text: str | None = Field(default=None)
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)

    posted_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None)

    raw: dict[str, Any] = Field(default_factory=dict, description="Unmodified payload.")

    def posted_datetime(self) -> datetime | None:
        if self.posted_date is None:
            return None
        return datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)

"""The raw record a Corporate Staffing posting is parsed into.

Measured 2026-10-18 across three detail pages. Everything comes from labelled
rows in the body::

    Date Posted: 16/10/2026
    Job Type: Full Time
    Employer: APA Life Assurance Company Ltd
    Salary: Open
    Location: Nairobi
    Deadline: 26/10/2026

* ``Salary`` reads ``"Open"`` / ``"Confidential"`` -- prose, not a figure.
* Dates are **dd/mm/yyyy** (Kenyan convention), not ISO and not mm/dd/yyyy.
  A parser that assumes ISO returns nothing for every posting.
* ``og:title`` IS the job title here, but ``<h1>`` is the same string and is
  closer to the data, so the h1 is preferred.
* No ``identifier``, no ``baseSalary``, no JSON-LD.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawCorporateStaffingJob(BaseModel):
    """One Corporate Staffing posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The slug, e.g. "accountant-financial-reporting-job-apa-life-assurance".
    source_job_id: str = Field(..., description="Corporate Staffing posting slug.")

    title: str = Field(..., description="Job title, from <h1>.")
    company_name: str = Field(default="Unknown employer")

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)

    salary_text: str | None = Field(default=None)

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

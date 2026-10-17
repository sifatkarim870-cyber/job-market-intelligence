"""The raw record a JobsNepal posting is parsed into.

Measured 2026-10-18 across two detail pages. Everything is markup extraction
from labelled rows::

    Job posted on 05 Oct, 2026 Apply before 18 Oct, 2026
    LOCATION Central Office
    Salary: Negotiable as per competence and experience.
    Position Type Full Time
    Experience 7+ years
    Category Accounting/Finance
    Posted Date 05 Oct, 2026

* ``Salary`` reads ``"Negotiable as per competence and experience."`` -- prose,
  not a figure.
* ``og:title`` / ``og:description`` are **site-wide** and must not be used.
* No ``identifier``, no JSON-LD, no ``baseSalary``.
* The ``<title>`` is ``"<Job Title> - <Company> - <id> - JobsNepal"``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobsNepalJob(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_job_id: str = Field(
        ..., description="JobsNepal posting id (numeric suffix of the slug)."
    )

    title: str = Field(..., description="Job title, from <h1>.")
    company_name: str = Field(default="Unknown employer")

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)
    industry: str | None = Field(default=None)

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

"""The raw record a Karriere.at posting is parsed into.

Measured 2026-10-18. The payload carries:

    @context, @type, title, description (HTML), datePosted, employmentType,
    hiringOrganization (name + sameAs), identifier (PropertyValue, value is a
    string), jobLocation (an array of Place), baseSalary (EUR, nested
    value.value shape), directApply

Traps, each measured:

* ``employmentType`` is a **list** (``[\"PART_TIME\"]``) -- the same shape as
  Angola Emprego, not the bare string Jobweb Ghana sends.
* ``identifier`` is a ``PropertyValue`` whose ``value`` is a **string**
  (\"10035663\"), not an int.
* ``jobLocation`` is an **array** of ``Place``.
* ``baseSalary`` nests ``value``/``minValue``/``maxValue``/``unitText`` under
  ``value`` -- the Apna/Mustakbil shape, a **seventh** distinct layout.
* ``datePosted`` carries a timezone offset (\"2026-10-17T08:23:08+02:00\").
* ``description`` is HTML.
* **No ``industry``** on the measured postings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawKarriereAtJob(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_job_id: str = Field(..., description="Karriere.at posting id (the numeric slug).")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_url: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    employment_type: list[str] | None = Field(default=None)
    industry: str | None = Field(default=None)

    salary_currency: str | None = Field(default=None)
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_unit_text: str | None = Field(default=None)

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

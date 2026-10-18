"""The raw record a Hiredly posting is parsed into.

Measured 2026-10-18 against a rendered ``my.hiredly.com`` detail page. The
whole record is one node of ``#__NEXT_DATA__``::

    props.pageProps.job
      title                 "Management Associate (CEO-Mentored Track)"
      location              "Petaling Jaya"
      stateRegion           "Selangor"
      salary                "4000 - 6000"        <- display string
      minYearsExperience    1
      maxYearsExperience    3
      company.name          "Uno Advisers"
      company.industry      "Financial Services"
      tracks[].title        "Corporate Finance / Investment"
      skills[].name         "Personal Finance", ...
      structuredJobData
        datePosted          "2026-09-16"
        validThrough        "2026-11-02T10:16:00+08:00"
        employmentType      "FULL_TIME"
        baseSalary.currency "MYR"
        baseSalary.value    {minValue: 4000, maxValue: 6000, unitText: "MONTH"}

Traps baked into the field set:

* ``salary`` is a *display string*. It reads ``"Undisclosed"`` when the
  employer published nothing, which is the majority of postings. Only
  ``structuredJobData.baseSalary`` is a figure.
* ``__NEXT_DATA__`` and the page's ``ld+json`` disagree about the address for
  the same posting, so the ``ld+json`` block is not read at all.
* ``description`` arrives as WYSIWYG-exported markdown-ish text: bullet
  underscores (``_ TWO Slots Open``) and ``**bold**``. It is cleaned, not
  trusted.
* ``similarJobs`` on the same page is a list of *other* postings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawHiredlyJob(BaseModel):
    """One Hiredly posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The full slug, e.g.
    #: "jobs-malaysia-uno-advisers-job-management-associate-ceo-mentored-track".
    source_job_id: str = Field(..., description="Hiredly posting slug.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_industry: str | None = Field(default=None)
    company_logo_url: str | None = Field(default=None)

    #: "Petaling Jaya, Selangor" -- city and state, both published.
    location: str | None = Field(default=None)
    country: str | None = Field(default="Malaysia")

    description: str | None = Field(default=None)
    requirements: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)
    job_category: str | None = Field(default=None, description="From tracks[].title.")
    skills: list[str] = Field(default_factory=list)

    min_years_experience: int | None = Field(default=None)
    max_years_experience: int | None = Field(default=None)

    #: None when the employer published nothing. Never parsed out of the
    #: "Undisclosed" display string.
    salary_min: int | None = Field(default=None)
    salary_max: int | None = Field(default=None)
    salary_currency: str | None = Field(default="MYR")
    #: "MONTH" is the only unitText measured. Anything else is left unmapped.
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

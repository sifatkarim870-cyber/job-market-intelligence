"""The raw record an ACBAR posting is parsed into.

ACBAR publishes **no structured data** -- no schema.org JSON-LD, no ``og:`` meta
tags. Everything comes from a ``<dl class="acbar-jd__info-table">`` of
label/value rows plus an ``<h1>``.

Measured 2026-10-18 across three postings, the info table carries::

    Type              "Full Time"
    Location          "Baghlan - Pull-e-Khumri", "Kabul"
    Category          "Education, Training"
    Published         "2026-10-14"          <- the real posting date
    Nationality       "Afghan" / "National"
    Gender            "Female" / "Male" / "Male/Female"
    Salary            "As Per Organization" / "Negotiable"   <- prose, not a number
    Contract Duration "Project Based" / "4 Months"
    Vacancy Number    "(05-PG-SDCO)"
    No of Job         "2"

and the closing date sits separately in ``.acbar-jd__deadline-label`` /
``.acbar-jd__deadline-value`` ("Deadline" / "2026-10-24").

The trap
--------
``.acbar-jd__body`` is 4680 characters and contains **six** ISO dates, all of
them belonging to **other** postings in a ``.acbar-jd__related`` carousel. The
tell was that the same ten dates came back from two *different* posting pages. A
naive "first date in the body" extraction therefore assigns a deadline from an
unrelated job. The related block is dropped before the text is taken; after that
**zero** dates remain in the body.

There is no company field: the employer appears only in the body prose ("About
the Company / Company Profile - Peyawray Rubaat Manufacturing Company"), which is
a sentence rather than a field.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawAcbarJobsJob(BaseModel):
    """One ACBAR posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from ``/en/jobs/details/<id>/<slug>``. Stable and always
    #: present, which makes it the key.
    source_job_id: str = Field(..., description="ACBAR posting id.")

    title: str = Field(..., description="Job title, from <h1>.")
    company_name: str = Field(default="Unknown employer")
    #: The ``Salary`` row verbatim -- "As Per Organization", "Negotiable". Kept
    #: so the decision not to store it is auditable.
    salary_text: str | None = Field(default=None)

    employment_type: str | None = Field(default=None, description="The 'Type' row.")
    industry: str | None = Field(default=None, description="The 'Category' row.")
    nationality: str | None = Field(default=None)
    gender: str | None = Field(default=None)
    contract_duration: str | None = Field(default=None)
    vacancy_number: str | None = Field(default=None)
    no_of_jobs: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    posted_date: date | None = Field(default=None, description="The 'Published' row.")
    closing_date: date | None = Field(default=None, description="The Deadline value.")

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None)

    #: Every label/value row, verbatim, so nothing measured is lost.
    info: dict[str, str] = Field(default_factory=dict)

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

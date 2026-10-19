"""The raw record a Jobs.ge posting is parsed into.

Measured 2026-10-18 against rendered ``jobs.ge`` pages.

Listing (``/en/jobs``), a plain HTML table whose header row is
``* | VIP Advertisements | | Provided By | Published | Deadline``::

    <a href="/en/?view=jobs&id=761321" class="vip">Senior IT Support/System Administrator</a>
    ... Geosoft Cloud | 16 October | 16 November

Detail (``/ge/?view=jobs&id=761321``), one-cell table rows::

    დასახელება: უფროსი IT მხარდაჭერის/სისტემის ადმინისტრატორი   "Ad title:"
    მომწოდებელი: Geosoft Cloud                              "Provided By:"
    გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი
                                        "Published: 16 October / Deadline: 16 November"
    <the full ad body, 4,421 characters>

Traps baked into the field set:

* The **English detail page is a stub** -- 548 characters ending in "See full
  text of this announcement in Georgian." Parsing it yields a title and an
  employer and nothing else.
* The **id is a query parameter**, not a path segment:
  ``/en/?view=jobs&id=761321``.
* **Dates carry no year**, and the months are Georgian.
* **No salary field and no location field.** Both appear only in prose, and
  prose is not scraped.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobsGeJob(BaseModel):
    """One Jobs.ge posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from ``?view=jobs&id=761321``, as a string.
    source_job_id: str = Field(..., description="Jobs.ge numeric ad id.")

    #: Georgian, matching the description below it.
    title: str = Field(..., description="Job title, from the Georgian detail page.")
    #: English, from the listing. Stored separately rather than substituted:
    #: the description is Georgian and a mismatch between the two would be worse
    #: than admitting one of them is a translation of the other.
    title_en: str | None = Field(default=None)

    company_name: str = Field(default="Unknown employer")
    description: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default="Georgia")

    employment_type: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    #: From the listing's own Published / Deadline columns, before the detail
    #: page is fetched. Kept as hints; the detail page is authoritative.
    listing_published: str | None = Field(default=None)
    listing_deadline: str | None = Field(default=None)

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

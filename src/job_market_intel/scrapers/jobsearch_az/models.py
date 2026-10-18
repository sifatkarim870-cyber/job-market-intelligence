"""The raw record a JobSearch.az posting is parsed into.

Measured 2026-10-18 against a rendered detail page::

    <h1 class="vacancy__title">       "Resepşionist / Receptionist (Stomatoloji Klinika)"
    <h1 class="company__title">       "German Dental Clinic"
    <span class="vacancy__deadline">  "Son tarix 17 noy 2026"
    <span class="company__industry"><a>Biznes, İdarəetmə və İnsan Resursları</a></span>
    <div id="content_block">          the description

Traps baked into the field set:
* The first ``<h1>`` on the page is ``company__title``, not the job title.
* The posting date exists **only** on the listing card, as a year-less label
  ("16 okt") or a relative word ("Bu gün", "Dünən").
* There is **no salary**. The listing renders a ``li.money`` per card but its
  text is injected after the DOM snapshot, so it is always empty.
* There is **no JSON-LD and no ``og:`` meta tags**.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobSearchAzJob(BaseModel):
    """One JobSearch.az posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "amper-elektrik-surucu-150511".
    source_job_id: str = Field(..., description="JobSearch.az posting slug.")

    title: str = Field(..., description="Job title, from h1.vacancy__title.")
    company_name: str = Field(default="Unknown employer")

    #: Never published on the detail page. Left None so geographic resolution
    #: resolves the country alone rather than inventing a city.
    location: str | None = Field(default=None)
    country: str | None = Field(default="Azerbaijan")

    description: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)
    industry: str | None = Field(default=None, description="The vacancy's category.")
    employer_industry: str | None = Field(default=None, description="The employer's sector.")

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

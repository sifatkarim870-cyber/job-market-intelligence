"""The raw record a JobsIreland.ie posting is parsed into.

Measured 2026-10-19 against live responses.

Listing (the HTML fragment from ``/Jobsireland.API/JobsIreland/BrowseJobs``),
one hidden input per field, flat in document order, one set per card::

    JobId         2475739
    JobReference  #CES-2475739
    CompanyLogo   (usually empty)
    JobTitle      Caretaker of Sports Ground (Elton) - CE Scheme - SLIABH RI LIMITED
    Location      Elton, Knocklong, Co. Limerick, E34 Y540
    StartDate     2026-10-19T12:05:30
    EndDate       2026-11-30T00:00:00
    VacancyTypeId 3

Detail (``/en-US/job-Details?id=2475739``), a title and a
``ul.job-detail_list`` whose every ``<li>`` is labelled by its icon's ``alt``::

    <img alt="Image for Employer">   SLIABH RI LIMITED
    <img alt="Image for Job Ref">    Ref: #CES-2475739
    <img alt="Image for Location">   Elton, Knocklong, Co. Limerick
    <img alt="Image Position">       No of positions: 1
    <img alt="Image Part Time">      Community Employment Programme
    <img alt="Image Hours per week"> 19.5 hours per week
    <img alt="Image for Euro">       Community Employment Programme Rates
    <img alt="Image for Published">  Published On: 19 Oct 2026
    <img alt="Image for Closing">    Closing On: 30 Nov 2026

Traps baked into the field set:

* **The listing title embeds the employer.** ``JobTitle`` is
  ``"<title> - CE Scheme - <employer>"``, while the detail page's ``<h3>`` is
  the title alone and the employer is its own ``<li>``. The detail page is
  authoritative; the listing's copy is only a fallback.

* **Addresses are four comma parts**: ``"<premises>, <town>, Co. <County>,
  <Eircode>"``. 154 of 200 sampled addresses carry an Eircode. Stored raw, they
  resolve to nothing: ``split_location_segments`` splits on ``;`` and the comma
  fallback is built for a two-part "City, ST". Measured: **1 of 16** real
  addresses resolved before ``reduce_location`` trimmed them to "town, county",
  and **16 of 16** after.

* **Dublin carries its postal district** -- ``Dublin 8``, ``Dublin 12``,
  ``Dublin 2`` -- which ``ref.cities`` does not hold.

* **There is no salary.** ``alt="Image for Euro"`` is the euro icon beside the
  *label* of a link to a programme-wide rates page.

* **Vacancy types** are ``-1`` All, ``0`` Paid Position, ``3`` Community
  Employment Programme, ``4`` Apprenticeship, ``6`` Self Employed, ``10`` Work
  Placement Experience Programme. Measured mix over 600 cards: 3 -> 66%,
  0 -> 33%, 10 -> 1%.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: VacancyTypeId -> (label, employment_type_code or None). Measured from the
#: #VacancyTypeId select on the listing page, 2026-10-19.
VACANCY_TYPES: dict[str, tuple[str, str | None]] = {
    "-1": ("All job types", None),
    "0": ("Paid Position", "full_time"),
    "3": ("Community Employment Programme", "part_time"),
    "4": ("Apprenticeship", "apprenticeship"),
    "6": ("Self Employed", "freelance"),
    "10": ("Work Placement Experience Programme", "internship"),
}


class RawJobsIrelandJob(BaseModel):
    """One JobsIreland.ie posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric ad id from ``?id=2475739``, as a string.
    source_job_id: str = Field(..., description="JobsIreland.ie vacancy id.")

    #: From the detail page's ``<h3>`` -- title only, no employer. The listing's
    #: ``JobTitle`` is the fallback and it carries " - <scheme> - <employer>".
    title: str = Field(..., description="Job title.")
    #: The listing's raw ``JobTitle``, kept so the fallback path is auditable.
    listing_title: str | None = Field(default=None)

    company_name: str = Field(default="Unknown employer")
    description: str | None = Field(default=None)

    #: The raw mailing address, e.g.
    #: "MOTHER MCAULEY CENTRE, Curlew Road, Drimnagh, Dublin 12, D12 C432".
    location: str | None = Field(default=None)
    #: The address reduced to "town, county" -- what the geographic resolver
    #: can actually act on. See the module docstring.
    location_reduced: str | None = Field(default=None)
    country: str = Field(default="Ireland")

    reference: str | None = Field(default=None)
    positions: int | None = Field(default=None)
    hours_per_week: str | None = Field(default=None)
    vacancy_type_id: str | None = Field(default=None)
    vacancy_type_label: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    company_logo_url: str | None = Field(default=None)
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

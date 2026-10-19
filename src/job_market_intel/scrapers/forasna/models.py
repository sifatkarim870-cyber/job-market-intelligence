"""The raw record a Forasna posting is parsed into.

Measured 2026-10-19 against live responses.

Listing (``/وظائف-خالية?start=20``), 20 postings a page, each link shaped
``/job/p/<arabic-slug>-<id>``::

    /job/p/مسئول-تسويق-ومبيعات-خارجية-أون-تايم-سيستمز-مصر-المنيا-المنيا-444468

The **id is the trailing number of the slug**, and the JSON-LD
``identifier.value`` agrees with it.

Detail (``/job/p/<slug>``), a schema.org ``JobPosting``::

    title              مسئول تسويق ومبيعات خارجية
    identifier         {"@type": "PropertyValue", "name": "Forasna", "value": "444468"}
    datePosted         2026-10-19T20:27:15+03:00
    validThrough       2026-11-17T20:27:15+02:00
    employmentType     PART_TIME
    hiringOrganization {"@type": "Organization", "name": "أون تايم سيستمز",
                       "sameAs": "https://forasna.com/company/..."}
    jobLocation        {"@type": "Place", "address": {"@type": "PostalAddress",
                       "addressRegion": "المنيا", "addressLocality": "المنيا",
                       "addressCountry": "EG"}}
    baseSalary         {"@type": "MonetaryAmount", "currency": "EGP",
                        "value": {"@type": "QuantitativeValue", "minValue": 5000,
                                  "unitText": "MONTH", "maxValue": 8000}}
    description        (present on 44 of 60 sampled postings)

Traps baked into the field set:

* **The currency is per posting.** 18 of 60 declare EGP and one declares
  **USD** on an Egyptian board, so it is read from the record and never
  assumed.
* **The salary is monthly.** ``unitText`` is ``MONTH`` on every sampled
  posting that carries a figure.
* **The description is absent on 27% of postings.** The employer simply left
  the body empty; the page then shows only the structured "requirements"
  block. Nothing is invented to fill it.
* **``addressRegion`` can be a governorate of another country.** One sampled
  posting has ``addressRegion`` "أبها" -- Abha, in **Saudi Arabia** -- so the
  country comes from ``addressCountry``, never from the region.
* **Arabic spellings are inconsistent.** The same place appears as both
  "ابو حماد" and "أبو رواش" (with and without hamza), so exact city matching
  is partial by nature and is not papered over.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: schema.org employmentType -> the corpus's employment_type_code.
#: "OTHER" and anything unrecognised become None rather than a guess.
EMPLOYMENT_TYPES: dict[str, str | None] = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "contract",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "VOLUNTEER": "volunteer",
    "PER_DIEM": "freelance",
    "OTHER": None,
}

#: schema.org unitText -> the corpus's pay_period vocabulary. The latter is
#: fixed by a CHECK constraint on salary.job_salaries.pay_period, so a value
#: outside it aborts the shared transaction.
UNIT_TO_PAY_PERIOD: dict[str, str] = {
    "MONTH": "monthly",
    "YEAR": "yearly",
    "HOUR": "hourly",
    "DAY": "daily",
    "WEEK": "weekly",
}


class RawForasnaJob(BaseModel):
    """One Forasna posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_job_id: str = Field(..., description="Forasna posting id.")
    title: str = Field(..., description="Job title, in Arabic.")
    company_name: str = Field(default="Unknown employer")
    description: str | None = Field(default=None)

    #: "locality, region" -- the form the geographic resolver can act on.
    location: str | None = Field(default=None)
    locality: str | None = Field(default=None)
    region: str | None = Field(default=None)
    country: str | None = Field(default="EG")

    employment_type: str | None = Field(default=None)
    employment_type_code: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    salary_min: int | None = Field(default=None)
    salary_max: int | None = Field(default=None)
    salary_currency: str | None = Field(default=None)
    pay_period: str | None = Field(default=None)

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

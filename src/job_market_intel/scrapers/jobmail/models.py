"""The raw record a JobMail posting is parsed into.

Measured 2026-10-19 against live responses.

Listing card (``/jobs/``), one ``div.results-item`` per posting::

    <div class="results-item tablinks" id="results-item-7568798">
      <div class="job-posted">04 September 2026</div>
      <a class="tablinks" href="/jobs/administration-pa-secretary/...-id-7568798">
        <h3>Designated Agent</h3>
      </a>
      <div class="job-info"><b>R20 000,00 - R30 000,00</b></div>
      <div>PER MONTH</div>
      <div class="job-location">Kwazulu-Natal</div>
      <span class="company">Bargaining Council for the Furniture
        Manufacturing Industry KwaZulu-Natal</span>

Detail (``/jobs/...-id-7568798``), a schema.org ``JobPosting``::

    title              Designated Agent
    description        1,888 characters of real body text
    datePosted         2026-09-04T08:55:35
    validThrough       2026-10-30T08:55:35
    employmentType     FULL_TIME
    industry           administration-pa-secretary, other administration/pa/secretary
    hiringOrganization {"name": "Bargaining Council ...", "url": "..."}
    identifier         {"name": "...", "value": "7568798"}
    jobLocation        {"addressLocality": "Kwazulu-Natal",
                        "addressRegion": "Kwazulu-Natal", "addressCountry": "ZA"}
    baseSalary         {"currency": "ZAR", "value": {"minValue": 20000,
                        "maxValue": 30000, "unitText": "MONTH"}}

Traps baked into the field set:

* **"Market Related" is a salary that is not a figure.** ``div.job-info`` holds
  either a rand range or the words "Market Related", which is the board
  saying a salary exists but is not published. Parsing it for digits would
  invent one; it is treated as no salary at all.
* **Rand amounts use a space as the thousands separator and a comma as the
  decimal**: ``R20 000,00 - R30 000,00``. The separator is sometimes a
  non-breaking space, so the parse normalises ``\\xa0`` first.
* **The location's granularity varies.** ``addressLocality`` is a city on some
  postings and a province on others, with ``addressRegion`` the same value.
  Both are in the corpus's South African reference data.
* **The card's date may carry a non-breaking space** ("04\\xa0September
  2026").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: schema.org employmentType -> the corpus's employment_type_code.
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

#: schema.org unitText -> the corpus's pay_period vocabulary, which is fixed by
#: a CHECK constraint on salary.job_salaries.pay_period.
UNIT_TO_PAY_PERIOD: dict[str, str] = {
    "MONTH": "monthly",
    "YEAR": "yearly",
    "HOUR": "hourly",
    "DAY": "daily",
    "WEEK": "weekly",
}

#: The board's way of saying "there is a salary, but we are not publishing
#: it". It sits in the same field as the amounts, so it has to be recognised
#: rather than parsed.
NON_NUMERIC_SALARY_MARKERS = frozenset(
    {
        "market related",
        "market-related",
        "negotiable",
        "competitive",
        "undisclosed",
        "not disclosed",
        "depending on experience",
    }
)


class RawJobMailJob(BaseModel):
    """One JobMail posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_job_id: str = Field(..., description="JobMail posting id.")
    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    description: str | None = Field(default=None)

    #: "locality, region" -- the form the geographic resolver can act on.
    location: str | None = Field(default=None)
    locality: str | None = Field(default=None)
    region: str | None = Field(default=None)
    country: str | None = Field(default="ZA")

    employment_type: str | None = Field(default=None)
    employment_type_code: str | None = Field(default=None)
    #: The board's own category, e.g. "administration-pa-secretary, other
    #: administration/pa/secretary".
    industry: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    salary_min: int | None = Field(default=None)
    salary_max: int | None = Field(default=None)
    salary_currency: str | None = Field(default=None)
    pay_period: str | None = Field(default=None)
    #: True when the board published a salary but not a figure ("Market
    #: Related"). Kept so the distinction is auditable rather than lost.
    salary_undisclosed: bool = Field(default=False)

    url: str | None = Field(default=None)
    company_url: str | None = Field(default=None)
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

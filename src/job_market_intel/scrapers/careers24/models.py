"""The raw record a Careers24 advert is parsed into.

Careers24's detail page publishes a schema.org ``JobPosting``. Measured on 8
postings (2026-10-15), 12 of 12 fields were present on every one:

    title, description, industry, identifier, datePosted, validThrough,
    employmentType, hiringOrganization, jobLocation

with ``baseSalary`` on 2 of 8.

Two shapes differ from the sibling schema.org sources in this project and are
handled explicitly rather than assumed:

* ``identifier`` is a ``PropertyValue`` whose ``name`` is the company and whose
  ``value`` is the advert id -- the same as Wellfound and Built In.
* ``baseSalary`` nests the figure **one level deeper than they do**::

      {"currency": "ZAR",
       "value": {"@type": "QuantitativeValue", "value": "180", "unitText": "DAY"}}

  There is no ``minValue``/``maxValue`` anywhere. A parser written for the
  Wellfound/Built In band shape reads ``None`` for both bounds here, which is
  not an error and not a log line -- it is a total, silent loss of the salary
  on every posting that publishes one. Measured over 40 postings on
  2026-10-16: 15 carry a salary, and a band-only parser would have recorded 0.

  A single figure is stored as both bounds, because one number is still a
  salary and a zero-width band keeps it inside the existing schema without
  inventing a range the employer did not state.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawCareers24Job(BaseModel):
    """One Careers24 advert, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric advert id, e.g. "2393572". Stable, so it is the natural key
    #: that makes re-runs idempotent. Named ``source_job_id`` to match every
    #: other source's raw model and what validation.common.validate_batch reads.
    source_job_id: str = Field(..., description="Careers24 advert id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    industry: str | None = Field(default=None, description="e.g. 'Admin', 'Engineering'.")
    employment_type: str | None = Field(default=None, description="e.g. FULL_TIME.")

    location: str | None = Field(default=None, description="'City, Region' from jobLocation.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'South Africa'.")
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)

    description: str | None = Field(default=None, description="HTML from the JSON-LD.")

    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_period: str | None = Field(default=None, description="e.g. 'YEAR'.")
    currency_iso_code: str | None = Field(default=None, description="e.g. 'ZAR'.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None, description="Which listing page found it.")

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

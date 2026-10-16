"""The raw record a Mustakbil posting is parsed into.

Mustakbil publishes a schema.org ``JobPosting`` at the top level of its JSON-LD.
A full example, measured 2026-10-16::

    {
      "@type": "JobPosting",
      "title": "AI & Digital Marketing S Instructors",
      "description": "<b>Job Description</b>: ...<ul><li>...</li></ul>",   # HTML
      "identifier": {"@type": "PropertyValue", "name": "Sharp Visions IT Company",
                     "value": "1436508"},                                  # a STRING
      "datePosted": "2026-10-16T07:40:53+00:00",
      "validThrough": "2027-01-16T19:00:00.0000000Z",     # 7-digit fraction!
      "employmentType": "FULL_TIME",
      "hiringOrganization": {"@type": "Organization", "name": "Sharp Visions IT Company",
                             "logo": "https://s.mustakbil.com/employers/<hash>.jpg"},
      "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress",
                       "addressLocality": "Rawalpindi", "addressCountry": "PK"}},
      "baseSalary": {"@type": "MonetaryAmount", "currency": "PKR",
                     "value": {"@type": "QuantitativeValue", "minValue": 40000,
                               "maxValue": 60000, "unitText": "MONTH"}},
      "experienceRequirements": {"@type": "OccupationalExperienceRequirements",
                                 "monthsOfExperience": 12},
      "directApply": false,
      "url": "https://www.mustakbil.com/jobs/job/1436508"
    }

Two shapes are worth calling out because they differ from the sibling sources:

* ``identifier.value`` is a **string** here, where Apna's is a JSON number.
* ``experienceRequirements`` is a nested
  ``{"@type": "OccupationalExperienceRequirements", "monthsOfExperience": N}``
  object rather than the bare string other boards emit.

``validThrough`` carries seven fractional-second digits
(``.0000000Z``), which Python's ``datetime.fromisoformat`` will not accept on
versions before 3.11 -- so the date is taken from the leading ``YYYY-MM-DD``
with a regex instead.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawMustakbilJob(BaseModel):
    """One Mustakbil posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The posting id, e.g. "1436508". The URL is authoritative, so it is what
    #: makes re-runs idempotent.
    source_job_id: str = Field(..., description="Mustakbil posting id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None, description="A plain URL string.")
    employment_type: str | None = Field(default=None, description="e.g. FULL_TIME.")

    months_of_experience: int | None = Field(
        default=None, description="From the OccupationalExperienceRequirements node."
    )
    experience_requirements_raw: str | None = Field(
        default=None, description="Whatever form experienceRequirements arrived in."
    )

    location: str | None = Field(default=None, description="'City, Region' from jobLocation.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'PK'.")
    city: str | None = Field(default=None)

    description: str | None = Field(default=None, description="HTML from the JSON-LD.")

    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_period: str | None = Field(default=None, description="'monthly' from MONTH.")
    currency_iso_code: str | None = Field(default=None, description="e.g. 'PKR'.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    direct_apply: bool | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_path: str | None = Field(default=None, description="Which listing path found it.")

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

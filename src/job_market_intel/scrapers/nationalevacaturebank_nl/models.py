"""The raw record a Nationale Vacaturebank ad page is parsed into.

Every field below comes from the ad page's schema.org ``JobPosting`` block,
measured on 2026-11-22::

    {"@type": "JobPosting",
     "title": "Back office support",
     "hiringOrganization": {"@type": "Organization", "name": "Michael Page"},
     "jobLocation": {"@type": "Place",
                     "address": {"@type": "PostalAddress",
                                 "addressLocality": "Rotterdam",
                                 "addressRegion": "Zuid-Holland",
                                 "addressCountry": "NL",
                                 "postalCode": "3011"},
                     "latitude": "51.92", "longitude": "4.48"},
     "datePosted": "2026-11-03T23:00:00Z",
     "validThrough": "2027-01-02T23:00:00Z",
     "employmentType": ["FULL_TIME", "PART_TIME"],
     "educationRequirements": {"@type": "EducationalOccupationalCredential",
                               "credentialCategory": "bachelor degree"},
     "experienceRequirements": {"@type": "OccupationalExperienceRequirements",
                                "monthsOfExperience": "48"},
     "workHours": "32 - 40 uur per week",
     "jobLocationType": null,
     "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
                    "value": {"@type": "QuantitativeValue",
                              "minValue": 3000, "maxValue": 3700,
                              "unitText": "MONTH"}},
     "description": "<p>...</p>"}

Traps pinned from the live pages:

* ``datePosted`` and ``validThrough`` are stamped at ``22:00Z``/``23:00Z`` --
  midnight in the Netherlands. They are converted to Europe/Amsterdam before
  the date is taken; reading the raw UTC date dates every ad one day early.
* ``employmentType`` is usually the list ``["FULL_TIME", "PART_TIME"]``, which
  is the board's default for "this role can be either". The cleaner only maps
  a value when the list names exactly one distinct type.
* ``baseSalary`` is the ad's **own** offer and is present on ~78% of ads
  measured. The separate ``Occupation`` block's ``estimatedSalary`` is the
  board's market estimate, so it is carried only in ``raw`` and never treated
  as a disclosed salary.
* Some ad pages are withdrawn: HTTP 410, or a 200 with no ``JobPosting``
  block. The client drops them before they reach this model.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawNationaleVacaturebankNlJob(BaseModel):
    """One Nationale Vacaturebank ad, as scraped from its JobPosting block."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The ad UUID from ``/vacature/<uuid>/<slug>``.
    source_job_id: str = Field(..., description="Ad UUID from the URL.")
    title: str = Field(..., description="Job title from the JobPosting block.")

    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None)

    #: ``jobLocation.address.addressLocality`` -- e.g. "Rotterdam".
    location_text: str | None = Field(default=None)
    #: ``jobLocation.address.addressRegion`` -- e.g. "Zuid-Holland".
    region: str | None = Field(default=None)
    #: ``jobLocation.address.addressCountry`` -- observed as "NL" on every ad.
    country: str | None = Field(default="Netherlands")
    postal_code: str | None = Field(default=None)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)

    description_html: str | None = Field(default=None)

    posted_date: dt.date | None = Field(default=None)
    closing_date: dt.date | None = Field(default=None)

    #: Raw schema.org employmentType values, e.g. ``["FULL_TIME", "PART_TIME"]``.
    employment_types: list[str] = Field(default_factory=list)
    work_hours: str | None = Field(default=None)
    #: ``educationRequirements.credentialCategory``, e.g. "bachelor degree".
    education_credential: str | None = Field(default=None)
    #: ``experienceRequirements.monthsOfExperience``.
    experience_months: int | None = Field(default=None)

    occupational_category: str | None = Field(default=None)
    industry: str | None = Field(default=None)

    #: ``"TELECOMMUTE"`` on ads the board marks fully remote; ``None`` otherwise.
    job_location_type: str | None = Field(default=None)
    direct_apply: bool | None = Field(default=None)

    salary_currency: str | None = Field(default="EUR")
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    #: ``hourly``/``daily``/``weekly``/``monthly``/``yearly`` from ``unitText``.
    salary_period: str | None = Field(default=None)
    #: The raw ``unitText`` (e.g. "MONTH"), kept for audit.
    salary_unit_raw: str | None = Field(default=None)
    #: True when the period was inferred rather than taken at face value: the
    #: amount carried no ``unitText``, or it carried ``MONTH`` while the
    #: magnitude made a month impossible (the board's hourly-rate-in-a-MONTH
    #: trap -- see the parser).
    salary_period_assumed: bool = Field(default=False)

    #: The ``Occupation`` block's market estimate, kept for audit only. schema.org
    #: allows it to be an object or a list of objects, and the board sends a list.
    estimated_salary: Any | None = Field(default=None)

    job_url: str | None = Field(default=None)
    listing_category: str | None = Field(default=None)

    raw: dict[str, Any] = Field(default_factory=dict, description="Verbatim payload.")

    @field_validator("title", "source_job_id", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    def posted_datetime(self) -> dt.datetime | None:
        if self.posted_date is None:
            return None
        return dt.datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)

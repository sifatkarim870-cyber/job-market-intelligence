"""The raw record an Apna posting is parsed into.

Apna publishes a schema.org ``JobPosting`` at the top level of its JSON-LD.
Measured over 30 postings on 2026-10-16, all 30 carried all 16 of:

    title, description, datePosted, validThrough, employmentType,
    hiringOrganization, identifier, applicantLocationRequirements, jobLocation,
    baseSalary, directApply, industry, occupationalCategory, url

with ``skills`` on 15 of 30 (0-11 entries) and ``experienceRequirements`` on 17.

Three shapes differ from every other source in this project, and each is handled
explicitly rather than assumed:

* ``identifier.value`` is an **integer** (``670861231``), not a string. Every
  other ``PropertyValue`` identifier here carries a string.
* ``baseSalary.value`` is a ``QuantitativeValue`` holding ``minValue``/
  ``maxValue``. The band is therefore nested under ``value.value`` -- a fourth
  distinct salary layout in this codebase, after Wellfound's and Built In's
  top-level band and Careers24's bare ``value.value`` scalar.
* ``addressCountry`` is the ISO code ``"IN"``, not a country name.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawApnaJob(BaseModel):
    """One Apna posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The posting id, e.g. "670861231". Apna emits it as a JSON number, so it
    #: is stringified here; it is what makes re-runs idempotent.
    source_job_id: str = Field(..., description="Apna posting id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None, description="A plain URL string.")
    industry: str | None = Field(default=None, description="e.g. 'Retail & eCommerce'.")
    occupational_category: str | None = Field(default=None)
    employment_type: str | None = Field(default=None, description="e.g. FULL_TIME.")

    skills: list[str] = Field(default_factory=list)
    experience_requirements: str | None = Field(default=None)

    location: str | None = Field(default=None, description="'City, Region' from jobLocation.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'IN'.")
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)
    postal_code: str | None = Field(default=None)
    street_address: str | None = Field(default=None)

    description: str | None = Field(default=None, description="Plain text from the JSON-LD.")

    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_period: str | None = Field(default=None, description="'monthly' from MONTH.")
    currency_iso_code: str | None = Field(default=None, description="e.g. 'INR'.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    direct_apply: bool | None = Field(default=None)
    applicant_country: str | None = Field(
        default=None, description="applicantLocationRequirements."
    )

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

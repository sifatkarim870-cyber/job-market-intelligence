"""The raw record a Built In posting is parsed into.

Built In's detail page publishes a schema.org ``JobPosting`` inside an
``@graph`` document. Measured on 12 postings (2026-10-15):

    always present -- title, description (2-6k chars), directApply, identifier,
    datePosted, employmentType, applicantLocationRequirements,
    hiringOrganization (name, sameAs, logo as an ImageObject), industry,
    jobBenefits (a list of strings), jobLocation, validThrough

    sometimes     -- baseSalary (4 of 12), jobLocationType ("TELECOMMUTE" or
                     null)

Three fields are deliberately kept apart rather than flattened:

* ``job_locations`` -- the posting's location, which is a single ``Place`` on
  most postings and a list on some.
* ``applicant_countries`` -- ``applicantLocationRequirements``, the countries
  the employer will accept applicants from. That is a different claim from
  where the job is, and merging them would assert the posting is open there.
* ``benefits`` -- a list of short strings, kept as a list so "Offers 401(K)"
  does not become one comma-mangled run-on sentence.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawBuiltInJob(BaseModel):
    """One Built In posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The trailing numeric id of ``/job/<slug>/<id>``, e.g. "11692055". The
    #: slug changes when the title is edited; the id does not, so it is the
    #: natural key that makes re-runs idempotent. Named ``source_job_id`` to
    #: match every other source's raw model and what
    #: validation.common.validate_batch reads.
    source_job_id: str = Field(..., description="Built In numeric job id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_page_url: str | None = Field(default=None, description="hiringOrganization.sameAs.")
    company_logo_url: str | None = Field(default=None)
    employment_type: str | None = Field(default=None)
    industries: list[str] = Field(
        default_factory=list,
        description=(
            "industry. A LIST on 21 of 24 postings measured and a bare string on "
            "3, so a scalar here would reject the majority."
        ),
    )
    direct_apply: bool | None = Field(default=None)
    is_remote: bool | None = Field(
        default=None,
        description="True when jobLocationType is TELECOMMUTE, else None (not False).",
    )

    locations: list[str] = Field(default_factory=list)
    location_countries: list[str] = Field(default_factory=list)
    coordinates: list[tuple[float, float]] = Field(
        default_factory=list, description="(lat, lon) per jobLocation, when given."
    )
    applicant_countries: list[str] = Field(
        default_factory=list,
        description="Countries the employer accepts applicants from. NOT the job's location.",
    )

    description: str | None = Field(default=None, description="HTML from the JSON-LD.")
    benefits: list[str] = Field(default_factory=list, description="jobBenefits; a list of strings.")

    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_period: str | None = Field(default=None, description="e.g. 'YEAR'.")
    currency_iso_code: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_path: str | None = Field(default=None, description="Which listing found it.")

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

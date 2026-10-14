"""The raw record a USAJOBS posting is parsed into.

USAJOBS delivers a posting in two pieces that share no field names: the API's
``MatchedObjectDescriptor`` (identity, organisation, salary, dates, location)
and the public job page's schema.org ``JobPosting`` JSON-LD (description,
qualifications, education requirements). Both are flattened into one record
here, because the cleaner and the repository should see one shape.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawUSAJobsJob(BaseModel):
    """One USAJOBS posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: e.g. "CEDC-26-13071989-MP". Stable and unique, so it is the natural key
    #: that makes re-runs idempotent. Named ``source_job_id`` to match every
    #: other source's raw model and what validation.common.validate_batch reads.
    source_job_id: str = Field(..., description="PositionID; the natural key.")

    title: str = Field(..., description="Position title.")
    organization_name: str | None = Field(
        default=None, description="Employing organisation, e.g. U.S. Army Corps of Engineers."
    )
    department_name: str | None = Field(default=None)
    sub_agency: str | None = Field(default=None)
    location_display: str | None = Field(default=None, description="Human-readable location.")
    country_code: str | None = Field(default=None, description="Country from PositionLocation.")
    city_name: str | None = Field(default=None)
    state_code: str | None = Field(default=None, description="CountrySubDivisionCode.")
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)

    description: str | None = Field(
        default=None, description="Job description HTML from the page's JSON-LD."
    )
    qualification_summary: str | None = Field(
        default=None, description="Qualification summary text from the API."
    )
    education_requirements: str | None = Field(default=None)
    job_category: str | None = Field(default=None, description="e.g. 'General Engineering'.")
    job_grade: str | None = Field(default=None, description="Pay grade, e.g. 'GS'.")
    employment_type: str | None = Field(default=None, description="'OTHER', 'FULL_TIME', ...")
    schedule_code: str | None = Field(default=None)

    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_period: str | None = Field(default=None, description="'Per Year', 'Per Hour', ..")
    currency_iso_code: str = Field(default="USD")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None, description="PositionURI.")
    apply_url: str | None = Field(default=None)
    search_keyword: str | None = Field(
        default=None, description="Keyword that surfaced this posting; provenance only."
    )
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

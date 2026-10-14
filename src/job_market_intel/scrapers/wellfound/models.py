"""The raw record a Wellfound posting is parsed into.

Wellfound's detail page carries a schema.org ``JobPosting`` JSON-LD block that
is unusually complete -- 14 of 14 measured fields present on every posting
sampled on 2026-10-14 -- so most of this model is a direct projection of that
block rather than a reconstruction from markup.

Two fields are deliberately *not* flattened here:

* ``job_locations`` keeps the full list. A posting can name several offices
  (the sample named both Denver and San Francisco) and picking the first would
  silently drop a real location the employer stated.
* ``organization_locations`` is the company's office list, which is not the
  job's location. Conflating the two would put every job at a company in that
  company's head office.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawWellfoundJob(BaseModel):
    """One Wellfound posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from the URL and from the JSON-LD ``identifier.value``,
    #: e.g. "4839998". Stable, so it is the natural key that makes re-runs
    #: idempotent. Named ``source_job_id`` to match every other source's raw
    #: model and what validation.common.validate_batch reads.
    source_job_id: str = Field(..., description="Wellfound numeric job id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_website: str | None = Field(default=None, description="hiringOrganization.sameAs.")
    company_logo_url: str | None = Field(default=None)
    employment_type: str | None = Field(default=None, description="e.g. FULL_TIME.")
    industry: str | None = Field(default=None)

    #: Human-readable, comma-joined, one entry per office the posting names.
    locations: list[str] = Field(default_factory=list)
    location_countries: list[str] = Field(default_factory=list)
    organization_locations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The company's offices, each with coordinates. Not the job's location.",
    )

    description: str | None = Field(default=None, description="HTML from the JSON-LD.")
    benefits: str | None = Field(default=None, description="jobBenefits prose.")
    direct_apply: bool | None = Field(default=None)

    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_period: str | None = Field(default=None, description="e.g. 'YEAR', 'HOUR'.")
    currency_iso_code: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None, description="validThrough; absent in practice.")

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

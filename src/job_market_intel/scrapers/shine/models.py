"""The raw record a Shine.com posting is parsed into.

Measured 2026-10-20 against live shine.com pages:

Listing (``/job-search/jobs-in-india``), HTML cards shaped::

    /jobs/hiring-voice-over-artists-indian-languages/consultbae-india-private-limited/19798773

Detail (``/jobs/revenue-assurance/airtel-india/19525849``), a top-level
JSON-LD ``JobPosting`` block::

    {"@context": "https://schema.org", "@type": "JobPosting",
     "title": "Revenue Assurance",
     "hiringOrganization": {"@type": "Organization", "name": "Airtel India"},
     "identifier": {"@type": "PropertyValue", "value": "19525849"},
     "datePosted": "2026-09-04T22:32:23+05:30",
     "validThrough": "2026-11-03T22:32:21+05:30",
     "employmentType": "FULL_TIME",
     "experienceRequirements": {"@type": "OccupationalExperienceRequirements",
                                "monthsOfExperience": 36},
     "jobLocation": [{"@type": "Place",
                      "address": {"@type": "PostalAddress",
                                  "addressCountry": "IN",
                                  "addressLocality": "All India"}}],
     "skills": ["Financial analysis", "Risk management", ...],
     "industry": "Others",
     "description": "No job description at the moment! ..."}

Traps baked into the field set:

* **description may be a boilerplate string** ("No job description at the
  moment!"). Stored as-is; the cleaner decides whether it is substantial.
* **datePosted / validThrough are full ISO timestamps** with a +05:30
  offset -- parse directly, no year inference needed.
* **addressCountry is the ISO code 'IN'** -- matches geographic_resolution
  without normalization.
* **skills is a list of strings** on some postings, absent on others.
* **No __NEXT_DATA__** -- parse JSON-LD, not a Next.js hydration blob.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawShineJob(BaseModel):
    """One Shine.com posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from the URL path (``.../19525849``), as a string.
    source_job_id: str = Field(..., description="Shine.com numeric job id.")

    title: str = Field(..., description="Job title from JSON-LD.")
    company_name: str = Field(default="Unknown employer")
    description: str | None = Field(default=None)

    location: str | None = Field(
        default=None, description="addressLocality from JSON-LD (e.g. 'Chennai')."
    )
    country: str | None = Field(default="India")

    employment_type: str | None = Field(default=None)
    experience_months: int | None = Field(
        default=None, description="monthsOfExperience from JSON-LD."
    )
    skills: list[str] = Field(default_factory=list, description="Skills from JSON-LD.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None, description="Canonical detail URL.")
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

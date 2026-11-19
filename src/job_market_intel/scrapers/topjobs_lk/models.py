"""The raw record a TopJobs (topjobs.lk) posting is parsed into.

Measured on the live site on 2026-11-20:

  * The listing row carries more than the detail page does -- **title,
    employer, opening date, closing date and town** all come from the row,
    while the detail page carries the title, employer, closing date, job
    reference, an ``ad-status`` label set and the ad body. Neither page is a
    superset, so both are read and the detail page wins only where it has a
    value.
  * ``source_job_id`` is the board's own **job code** (``jc``), a zero-padded
    string such as ``0001573469``, and it is stable across pagination.
  * The listing title carries the **headcount** in trailing parentheses
    ("Call Center Executive  (20)"). The detail title does not, so the
    headcount is split off here rather than cleaned out downstream.
  * **Most ads are image-only.** Across 75 live ads sampled on 2026-11-20,
    71 had an ``<img>`` and no body text, 4 had readable text, and 1
    mentioned salary at all. ``description`` is therefore optional, and
    ``description_is_image`` records the reason it is absent instead of
    leaving the reader to guess.
  * Dates appear in **two different formats**: the listing writes
    ``Fri Nov 20 2026`` and the detail page writes ``03/12/2026``. Both are
    parsed rather than assuming one.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawTopJobsLkJob(BaseModel):
    """One TopJobs posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The board's job code (``jc``), e.g. "0001573469".
    source_job_id: str = Field(..., description="TopJobs job code.")

    title: str = Field(..., description="Job title, headcount suffix removed.")
    company_name: str = Field(default="Unknown employer")

    #: Number of openings when the listing states it, else ``None``.
    headcount: int | None = Field(default=None)

    #: The listing's "Job Description" column -- a short teaser ("Urgent"),
    #: never the ad body. Kept in ``raw`` rather than used as a description.
    listing_snippet: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default="Sri Lanka")

    description: str | None = Field(default=None)
    description_is_image: bool = Field(
        default=False,
        description="True when the ad body is an image and has no extractable text.",
    )

    employment_type: str | None = Field(
        default=None, description="Employment label, e.g. 'Full Time' or 'Contract'."
    )
    work_mode: str | None = Field(
        default=None, description="Onsite/Hybrid/Remote, from the ad-status labels."
    )
    labels: list[str] = Field(default_factory=list, description="Every ad-status label.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

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

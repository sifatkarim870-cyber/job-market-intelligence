"""The raw record a Job Bank Canada posting is parsed into.

Modelled on the search result plus its detail page, merged. Search results
carry a title, employer and date; the detail page carries the body text,
salary and application deadline. Both are flattened here so the cleaner and the
repository see one shape, like every other source's ``Raw*Job``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobBankJob(BaseModel):
    """One Job Bank posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from /jobsearch/jobposting/<id>. This is the natural key
    #: that makes re-runs idempotent -- Job Bank has no slug, and the URL also
    #: carries a rotating jsessionid that must never be part of identity.
    #: Named ``source_job_id`` to match the field every other source's raw
    #: model exposes and that ``validation.common.validate_batch`` reads.
    source_job_id: str = Field(..., description="Job Bank posting id, used as the natural key.")

    title: str = Field(..., description="Job title.")
    employer: str | None = Field(default=None, description="Employer name.")
    location: str | None = Field(default=None, description="City / province / territory text.")
    description: str | None = Field(
        default=None, description="Full description text from the detail page."
    )
    salary_text: str | None = Field(
        default=None, description="Salary as printed, e.g. '50.26 $/hour'."
    )
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    pay_period: str | None = Field(
        default=None, description="hourly / daily / weekly / monthly / annually."
    )
    posted_date: date | None = Field(default=None, description="Date the posting was published.")
    deadline_date: date | None = Field(default=None, description="Application deadline, if any.")
    #: Which occupational term surfaced this posting. Kept for provenance: it
    #: is how the search was driven, and the same posting legitimately appears
    #: under several terms.
    search_term: str | None = None
    url: str | None = Field(default=None, description="Canonical posting URL.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Unmodified payload.")

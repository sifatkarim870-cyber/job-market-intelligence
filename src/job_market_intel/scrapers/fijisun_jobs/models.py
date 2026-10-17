"""The raw record a Fiji Sun posting is parsed into.

Fiji Sun publishes **no structured data** -- no schema.org JSON-LD. Everything is
HTML extraction from a Tailwind-styled page.

Measured 2026-10-18 across three detail pages:

    <title>       "<Job Title> at <Company>  | Fiji Sun Jobs"
    <h1>          the bare title
    .mt-6.whitespace-pre-line.font-serif.text-neutral-700  the body
    .border.border-neutral-300 / aside.sticky  the "Job overview" block:
        Posted <relative phrase>
        Salary T.B.D.
        Openings N position
        Experience N+ yrs exp.
        Type Full-time
        Location Lautoka
        Closes <date>

Two traps, each measured:

1. **``og:title`` / ``og:description`` are SITE-wide** -- "Fiji Sun - Your
   Trusted Source for Fiji News" -- and must **not** be used. Trusting them would
   store the site's name as every job's title.

2. **The posting date is relative** ("Posted 1 week ago", "Posted 3 days ago")
   and the closing date is **absolute** ("Closes 5 November 2026"). The relative
   phrase is converted to a calendar date; the absolute one is read as a
   closing date. The posting date is therefore approximate, and that is recorded
   in ``raw_payload`` so a reader knows it was derived, not published.

``Salary`` reads ``"T.B.D."`` on every measured posting -- not a figure -- so no
salary is stored.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawFijiSunJobsJob(BaseModel):
    """One Fiji Sun posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "advertising-sales-executive-west-930m7".
    source_job_id: str = Field(..., description="Fiji Sun posting slug.")

    title: str = Field(..., description="Job title, from <h1>.")
    company_name: str = Field(default="Unknown employer")

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    employment_type: str | None = Field(default=None)
    category: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)
    #: The relative phrase the date was derived from, e.g. "1 week ago".
    posted_phrase: str | None = Field(default=None)

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


def _parse_relative_posted(phrase: str | None, today: date) -> date | None:
    """'1 week ago' / '3 days ago' / '2 months ago' -> a calendar date."""
    if not phrase:
        return None
    import re

    m = re.search(r"(\d+)\s+(day|week|month)s?\s+ago", phrase, re.I)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "day":
        delta = timedelta(days=n)
    elif unit == "week":
        delta = timedelta(weeks=n)
    else:
        delta = timedelta(days=n * 30)
    return today - delta

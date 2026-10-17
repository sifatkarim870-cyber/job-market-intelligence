"""The raw record a Job in Rwanda posting is parsed into.

Job in Rwanda publishes **no structured data at all** -- no schema.org
JSON-LD, no ``og:`` meta tags. Measured 2026-10-18 across three detail pages:
everything comes from ordinary markup.

    <title>          "<Job Title> | Job in Rwanda"   -> the title, before the bar
    .node__content   the posting body
    .field--name-body site boilerplate, NOT part of the posting

Two absences that shape the model, and both are facts about the board:

* **No posting date, anywhere.** Of six detail pages inspected, four carry no
  date at all, and the two that do carry one only ever carry a **deadline**, in
  prose::

      "The deadline for submission of applications is 19 October 2026 at 5:00 PM"
      "Application deadline Sunday 25 October 2026"
      "Application Deadline 28 November 2026 ."

  So ``posted_date`` is **always** ``None``. Only a date inside an explicitly
  deadline-shaped phrase is recorded, and it goes to ``closing_date``. A regex
  that took the first date on the page would have written a closing date into
  ``posting_date`` -- a claim the site never makes.
* **No company field.** The employer appears only inside the posting prose
  ("The Management of RATWA SACCO HUYE informs all qualified..."), which is not
  a field. ``company_name`` stays "Unknown employer" rather than being guessed
  out of a sentence.

There is no salary either.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawJobInRwandaJob(BaseModel):
    """One Job in Rwanda posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "accountant-172". Always present and stable.
    source_job_id: str = Field(..., description="Job in Rwanda posting slug.")

    title: str = Field(..., description="Job title, from <title> before the bar.")
    #: Always "Unknown employer": the board exposes no company field, and the
    #: employer is only inferable from prose.
    company_name: str = Field(default="Unknown employer")

    location: str | None = Field(default=None, description="Free text, e.g. 'Kigali'.")
    country: str | None = Field(default=None)

    description: str | None = Field(default=None)

    #: **Always None.** The site publishes no posting date. See the module
    #: docstring -- every date on these pages is a deadline.
    posted_date: date | None = Field(default=None)
    #: Only set from an explicitly deadline-shaped phrase.
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None)

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

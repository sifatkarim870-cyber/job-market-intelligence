"""The raw record an Alfred posting is parsed into.

Alfred publishes a schema.org ``JobPosting`` at the top level of its detail
page's JSON-LD. Measured over 10 postings on 2026-10-16:

======================  =========================================
field                    coverage
======================  =========================================
``title``                10/10
``description``          10/10  (17-2656 characters, HTML)
``datePosted``           10/10
``validThrough``         10/10  but **null on at least one**
``hiringOrganization``   10/10  ``name`` + ``logo`` as a URL string
``directApply``          10/10
``employmentType``       10/10  FULL_TIME 9, PART_TIME 1
``jobLocation``          7/10
``baseSalary``           **0/10**
``identifier``           **0/10**
======================  =========================================

Two absences drive the design of this model, and both are facts about the
board rather than parser gaps:

* **There is no ``identifier``.** Nothing in the payload names the posting, so
  the stable key is the URL slug. Using the slug is also what makes re-runs
  idempotent, because the numeric suffix in some slugs (``...-177-4``) is part
  of the slug and not a database id.

* **There is no ``baseSalary`` on any measured posting.** Alfred publishes no
  salary at all, so every field about salary is optional and stays ``None``, and
  ``salary_disclosed`` is always ``False``. There is no ``pay_period`` to map
  and nothing that could reach ``ck_job_salaries_pay_period``.

``validThrough`` is nullable in the source, so ``closing_date`` is too.

``jobLocation`` is absent on 3 of 10, which is why the cleaner keeps a
country-only label rather than dropping the row -- see
``SOURCE_HOME_COUNTRY``, which supplies Iceland for exactly that case.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawAlfredJob(BaseModel):
    """One Alfred posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "adstod-a-tannlknastofu". The payload carries no
    #: identifier of any kind, so this is the only stable key available.
    source_job_id: str = Field(..., description="Alfred URL slug.")

    title: str = Field(..., description="Job title, in Icelandic.")
    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None, description="A plain URL string.")
    employment_type: str | None = Field(default=None, description="e.g. FULL_TIME.")

    location: str | None = Field(default=None, description="'City' from jobLocation.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'Iceland'.")
    city: str | None = Field(default=None)

    description: str | None = Field(default=None, description="HTML from the JSON-LD.")

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None, description="validThrough; nullable here.")

    direct_apply: bool | None = Field(default=None)

    url: str | None = Field(default=None)
    slug: str | None = Field(default=None)

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

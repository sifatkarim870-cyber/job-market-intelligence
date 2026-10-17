"""The raw record a Jobweb Ghana posting is parsed into.

Jobweb Ghana publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page. Measured over 5 postings
on 2026-10-18, the payload carries::

    @context, @type, title, description, datePosted, validThrough,
    employmentType, hiringOrganization (name + sameAs), jobLocation
    (streetAddress, addressLocality, postalCode, addressRegion), baseSalary

* **No ``identifier``**, so the URL slug is the key -- which is also what makes
  re-runs idempotent.
* ``employmentType`` is the bare string ``"FULL_TIME"`` here (contrast Angola
  Emprego, which sends a list).
* ``baseSalary`` nests ``value``/``minValue``/``maxValue``/``unitText`` under
  ``value`` -- a **seventh** distinct layout in this codebase.
* ``datePosted`` has **no timezone** ("2026-10-16T12:56:18"); ``validThrough``
  is midnight-aligned ("2026-11-07T00:00:00").
* The description carries literal ``\\r\\n`` sequences.

The salary is a **site-wide placeholder** -- see the module docstring and
:data:`_SITE_DEFAULT_SALARY`. It is parsed, recorded for audit, and then
rejected by the cleaner.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _strip_types(node: Any) -> Any:
    """Drop every ``@type`` key, recursively.

    Used to compare a ``baseSalary`` block against the site-wide placeholder.
    Stripping rather than copying ``@type`` into the stored constant means the
    comparison survives a board adding or dropping a type annotation, instead of
    the guard quietly ceasing to fire.
    """
    if isinstance(node, dict):
        return {k: _strip_types(v) for k, v in node.items() if k != "@type"}
    if isinstance(node, list):
        return [_strip_types(v) for v in node]
    return node


def _canonical(node: Any) -> str:
    """A stable string form for comparison."""
    return json.dumps(_strip_types(node), sort_keys=True, default=str)


#: The site-wide placeholder salary seen on **5 of 5** measured postings,
#: spanning a Chief Executive Officer, a CCTV Controller and an Accounts Clerk.
#:
#: Kept as data, not prose, so the parser can *compare against it* rather than
#: trusting a comment. A Chief Executive and a CCTV guard do not share one salary
#: band, and ``value`` duplicating ``minValue`` is the signature of a template.
_SITE_DEFAULT_SALARY = _canonical(
    {
        "currency": "GHS",
        "value": {
            "value": "1500",
            "minValue": "1500",
            "maxValue": "8000",
            "unitText": "MONTH",
        },
    }
)


class RawJobwebGhanaJob(BaseModel):
    """One Jobweb Ghana posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The URL slug, e.g. "accounts-clerk-l-t-company". The board publishes no
    #: ``identifier``, so this is the only stable key.
    source_job_id: str = Field(..., description="Jobweb Ghana posting slug.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    company_url: str | None = Field(default=None, description="hiringOrganization.sameAs.")
    industry: str | None = Field(default=None)
    employment_type: str | None = Field(default=None)

    location: str | None = Field(default=None)
    country: str | None = Field(default=None)
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)
    postal_code: str | None = Field(default=None)

    description: str | None = Field(default=None)

    salary_currency: str | None = Field(default=None)
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    salary_unit_text: str | None = Field(default=None)
    #: The ``baseSalary`` block as received, for audit.
    salary_raw: dict[str, Any] | None = Field(default=None)

    posted_date: date | None = Field(default=None)
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

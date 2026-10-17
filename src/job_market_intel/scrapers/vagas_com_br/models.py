"""The raw record a Vagas.com.br posting is parsed into.

Vagas.com.br publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page. Measured over 3
postings on 2026-10-18, the payload carries::

    @context, @type, title, description, datePosted, validThrough,
    hiringOrganization (name), identifier (PropertyValue), jobBenefits,
    jobLocation (address: locality, region, country)

and on some postings one more::

    baseSalary  {currency: BRL, value: {unitText: MONTH, minValue, maxValue}}

Traps, each measured:

* ``addressCountry`` is the **name** ``"Brasil"``, not the ISO code ``"BR"``.
* ``identifier`` is ``{"@type": "PropertyValue", "name": ..., "value": <int>}``
  -- ``value`` is an **int**, so it needs ``str()``.
* ``baseSalary`` nests ``unitText``/``minValue``/``maxValue`` **flat** under
  ``value``, unlike Apna/Mustakbil which nest a further ``value`` beneath it.
  It is present on roughly one posting in three, so salary coverage is partial
  by nature and must not be read as a parser gap.
* **No ``employmentType`` and no ``industry``** on any measured posting.

The JSON-LD block is **malformed on some pages** (raw control characters), so
the parser attempts a strict ``json.loads`` first and falls back to
``json.loads(block, strict=False)``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawVagasComBrJob(BaseModel):
    """One Vagas.com.br posting, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The posting id as a string, e.g. "2831966". ``identifier.value`` is an
    #: **int** in the payload, so ``str()`` is applied at parse time.
    source_job_id: str = Field(..., description="Vagas.com.br posting id.")

    title: str = Field(..., description="Job title.")
    company_name: str = Field(default="Unknown employer")
    industry: str | None = Field(default=None)
    employment_type: str | None = Field(default=None)
    #: Comma-separated benefits string, e.g. "Vale-refeição, Assistência médica".
    job_benefits: str | None = Field(default=None)

    location: str | None = Field(default=None, description="'City, Region'.")
    country: str | None = Field(default=None, description="addressCountry, e.g. 'Brasil'.")
    city: str | None = Field(default=None)
    region: str | None = Field(default=None)

    description: str | None = Field(default=None, description="Plain text from JSON-LD.")

    salary_currency: str | None = Field(default=None, description="e.g. 'BRL'.")
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    #: schema.org ``unitText``, e.g. "MONTH". Empty string is dropped rather
    #: than guessed at -- see the Alfred precedent.
    salary_unit_text: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    closing_date: date | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None, description="Which listing page found it.")

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

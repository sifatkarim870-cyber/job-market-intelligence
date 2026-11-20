"""The raw record a L'Express Petites Annonces ad is parsed into.

L'Express Petites Annonces publishes **no structured data** -- no schema.org
JSON-LD. Everything is Tailwind markup extraction. Measured 2026-11-21 on
``/annonce/20261116-1794825510``::

    <h1 class="text-2xl font-bold w-[65%]">Pool Attendant - Azuri (Roches Noires)</h1>
    <p class="text-xs lg:text-md font-bold">Ref: 20261116-1794825510</p>
    <p class="text-sm text-gray-500">Emplois  &gt; Full-Time</p>
    <p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>
    <p class="text-lg">&lt;body&gt;</p>
    <p class="text-sm text-gray-500">Localisation: Roches Noires</p>

Traps pinned from the live pages:

* ``<title>`` is the site-wide ``"L'Express Petites Annonces"`` and must not
  be used as the job title.
* The breadcrumb and the ``Localisation:`` line share the exact class
  ``text-sm text-gray-500``; the breadcrumb is the one containing ``>``.
* Body contact emails are Cloudflare-obfuscated (``__cf_email__``), so
  ``get_text`` yields the literal ``"[email protected]"`` -- the decoded
  address is recovered from ``data-cfemail`` for audit.
* There is no employer field and no salary field; both are best-effort from
  the body / Maps query.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawLexpressMuJob(BaseModel):
    """One L'Express Petites Annonces ad, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The board's own token from the URL, e.g. "20261116-1794825510".
    source_job_id: str = Field(..., description="Ad token /annonce/<token>.")

    title: str = Field(..., description="Job title, from <h1>.")
    company_name: str = Field(default="Unknown employer")

    location: str | None = Field(default=None)
    country: str | None = Field(default="Mauritius")

    description: str | None = Field(default=None)

    #: "Full-Time" / "Part-Time" as printed after the "Emplois >" breadcrumb.
    employment_type: str | None = Field(default=None)
    #: The raw breadcrumb head, e.g. "Emplois".
    category: str | None = Field(default=None)

    salary_text: str | None = Field(default=None)
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    #: "monthly" / "yearly" / "weekly" / "daily" / "hourly", best effort.
    salary_period: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    #: The "Ref:" token printed on the detail page.
    reference: str | None = Field(default=None)

    phone: str | None = Field(default=None)
    contact_emails: list[str] = Field(default_factory=list)

    #: The remote-work phrase found in the body, if any.
    remote_phrase: str | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None)

    raw: dict[str, Any] = Field(default_factory=dict, description="Unmodified payload.")

    def posted_datetime(self) -> datetime | None:
        if self.posted_date is None:
            return None
        return datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)

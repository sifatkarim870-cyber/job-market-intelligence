"""The raw record a Revolico (Cuba) ad is parsed into.

Revolico publishes **no structured job data** -- no schema.org JSON-LD and no
employer or salary field. Everything comes from the Apollo cache the Next.js
page embeds. Measured 2026-11-21 on ``/item/se-busca-custodio-de-la-finca-55794055``::

    {"__typename": "AdType", "id": "55794055",
     "title": "Se busca: Custodio de La Finca",
     "description": "Se busca: Custodio de La Finca\\n_\\n...",
     "price": 1000, "currency": "CUP",
     "province": {"__ref": "ProvinceType:1"},
     "municipality": {"__ref": "MunicipalityType:43"},
     "subcategory": {"__ref": "CategoryType:1301"},
     "updatedOnByUser": "2026-11-20T20:51:46.137Z",
     "phoneInfo": {"firstPhone": {"prefix": "+53", "number": "53310760"}}, ...}

Traps pinned from the live pages:

* There is **no original posting date**; only ``updatedOnByUser`` (the last
  "bump"), which is what :attr:`posted_date` carries.
* There is **no employer**. The ad's ``name`` is the poster, kept as
  :attr:`poster_name`; the employer stays "Unknown employer".
* ``price``/``currency`` are unreliable (55 of 102 sampled ads carry none and
  many of the rest carry a placeholder ``1``), so they are retained on the model
  for ``raw_payload`` only and never become a disclosed salary.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawRevolicoCuJob(BaseModel):
    """One Revolico (Cuba) ad, as scraped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The numeric id from the URL, e.g. "55794055".
    source_job_id: str = Field(..., description="Ad id from /item/<slug>-<id>.")

    title: str = Field(..., description="Job title, from AdType.title.")
    company_name: str = Field(default="Unknown employer")

    #: The poster's display name (AdType.name). Not an employer.
    poster_name: str | None = Field(default=None)

    #: "Municipality, Province" when known, else "Cuba".
    location: str | None = Field(default=None)
    province: str | None = Field(default=None)
    municipality: str | None = Field(default=None)
    country: str | None = Field(default="Cuba")

    description: str | None = Field(default=None)

    #: The subcategory title, e.g. "Ofertas de Empleo".
    category: str | None = Field(default=None)
    subcategory_slug: str | None = Field(default=None)

    #: Raw AdType price/currency. Kept for audit; never a disclosed salary.
    price: float | None = Field(default=None)
    price_currency: str | None = Field(default=None)

    posted_date: date | None = Field(default=None)
    #: The raw "updated on" ISO timestamp printed by the board.
    updated_on: str | None = Field(default=None)

    phone: str | None = Field(default=None)

    #: The remote-work phrase found in the body, if any.
    remote_phrase: str | None = Field(default=None)

    url: str | None = Field(default=None)
    listing_page: int | None = Field(default=None)

    raw: dict[str, Any] = Field(default_factory=dict, description="Unmodified payload.")

    def posted_datetime(self) -> datetime | None:
        if self.posted_date is None:
            return None
        return datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)

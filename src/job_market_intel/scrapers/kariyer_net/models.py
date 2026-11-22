"""Raw record for one Kariyer.net posting.

Field values are merged from the search gateway (identity, employer, the
listing-side ``positionTypeText``) and the detail gateway (body, dates, work
model, candidate criteria). ``raw`` keeps the verbatim merged payload so
nothing the API said is discarded.

Dates arrive in two shapes and both are handled: the detail endpoint writes
``postingDate`` as ISO ``YYYY-MM-DD`` while the listing writes ``dd.mm.yyyy``;
``closingDateNumeric`` is ``dd.mm.yyyy``. Every value is optional at the model
level except identity and title, because a single malformed record must be
skipped, not fatal.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: ``dd.mm.yyyy`` as the listing and ``closingDateNumeric`` write it.
_DOTTED_DATE = "%d.%m.%Y"


def _parse_date(value: Any) -> dt.date | None:
    """Parse an ISO ``YYYY-MM-DD`` or Turkish ``dd.mm.yyyy`` date, or ``None``."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in (_DOTTED_DATE, "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class RawKariyerNetJob(BaseModel):
    """One Kariyer.net posting, merged from the two gateways."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_job_id: str = Field(..., description="Kariyer.net ``jobId`` as a string.")
    title: str = Field(..., description="Job title.")

    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None)

    #: ``"<city>, <country>"`` built from the detail ``locations`` list, e.g.
    #: ``"İstanbul(Asya), Türkiye"``. Falls back to ``locationText``.
    location_text: str | None = Field(default=None)

    #: The body as the board stores it: HTML in ``description_html``, plain
    #: text in ``description_text``. Both are kept; the cleaner prefers HTML.
    description_html: str | None = Field(default=None)
    description_text: str | None = Field(default=None)

    posting_date: dt.date | None = Field(default=None)
    closing_date: dt.date | None = Field(default=None)

    #: Absolute ``https://www.kariyer.net/is-ilani/<slug>-<id>`` URL.
    job_url: str | None = Field(default=None)

    #: ``workType`` (English, e.g. ``FullTime``) and ``workTypeText`` (Turkish,
    #: e.g. ``Tam Zamanlı``). Either can be missing.
    employment_type_raw: str | None = Field(default=None)
    employment_type_text: str | None = Field(default=None)

    #: ``workModel`` (``OnSite``/``Remote``/``Hybrid``) and the boolean flag.
    work_model_raw: str | None = Field(default=None)
    is_remote_work: bool | None = Field(default=None)

    position_level_text: str | None = Field(default=None)
    education_level_text: list[str] = Field(default_factory=list)
    experience_text: str | None = Field(default=None)

    #: English position name (``positionNameEn``) plus sector names, joined, for
    #: the shared category mapper.
    job_category_raw: str | None = Field(default=None)
    company_sector: str | None = Field(default=None)

    salary_budget: dict[str, Any] | None = Field(default=None)

    listing_page: int | None = Field(default=None)

    raw: dict[str, Any] = Field(default_factory=dict, description="Verbatim merged payload.")

    @field_validator("title", "source_job_id", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("posting_date", "closing_date", mode="before")
    @classmethod
    def _coerce_date(cls, value: Any) -> Any:
        return _parse_date(value)

    @field_validator("education_level_text", mode="before")
    @classmethod
    def _coerce_education(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if str(item).strip()]
        return []

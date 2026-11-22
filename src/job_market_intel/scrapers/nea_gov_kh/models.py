"""The raw record a National Employment Agency (Cambodia) vacancy is parsed into.

Every field comes from the server-rendered detail page measured on
2026-11-22::

    <span id="vacancyTitle">អ្នកដេរ</span>
    <div class="tit_box">
      <span class="tit">ហ្សេតអិម ហ្វ៊ូតវែរ (ខេមបូឌា) ឯ.ក</span>
    </div>
    <div class="cont">
      <strong class="tit">ប្រាក់បៀវត្ស</strong><span class="con">ខែ $210~$250</span>
    </div>
    <div class="form_wrap">
      <div class="form_title"><h3>ព័ត៌មានជ្រើសរើសកម្លាំងពលកម្ម</h3></div>
      <div class="view_form">
        <strong class="title">រយៈពេលជ្រើសរើស</strong>
        <p class="cont_box">20/11/2026 ~ 13/02/2027</p>
      </div>
    </div>

Traps pinned from the live pages:

* The detail page is one rendered document; there is no schema.org block, so
  every value is label-keyed HTML. Khmer labels are matched after zero-width
  spaces are removed (the board sprinkles ``U+200B`` inside words).
* ``អាសយដ្ឋាន`` (address) appears twice: the employer's address in the summary
  block and the **job centre's** address near the bottom. The first non-empty
  value is the employer's, and that is the one used.
* The workplace is encoded as ``<vacancies> / <province>`` inside
  ``ចំនួនកម្លាំងពលកម្មត្រូវជ្រើសរើស / ទីកន្លែងធ្វើការ``; the province is the
  part after the slash, and the full employer address is the fallback.
* Salaries are USD per month. A dollar sign is part of the text, not a
  different currency: Cambodia's labour market quotes in dollars.
* The description section is often a bare placeholder
  (``Job Descriptions Responsibilities Duties``). When the rendered text is
  that short the parser composes a factual description from the structured
  fields so the column is never a one-line placeholder.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawNeaGovKhJob(BaseModel):
    """One NEA Cambodia vacancy, as scraped from its detail page."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    #: The 32-hex ``condSeq`` from ``/vacancy/view.do?condSeq=...``.
    source_job_id: str = Field(..., description="The board's condSeq id.")
    title: str = Field(..., description="Title from #vacancyTitle.")

    company_name: str = Field(default="Unknown employer")
    company_logo_url: str | None = Field(default=None)

    #: The province from the workplace pair, or the employer address.
    location_text: str | None = Field(default=None)
    region: str | None = Field(default=None)
    country: str | None = Field(default="Cambodia")
    #: The complete employer address, kept separately from location_text.
    address: str | None = Field(default=None)

    description_html: str | None = Field(default=None)

    #: The start of the recruitment window (``រយៈពេលជ្រើសរើស``).
    posted_date: dt.date | None = Field(default=None)
    #: The end of the recruitment window.
    closing_date: dt.date | None = Field(default=None)

    #: The board's job-type text, e.g. ``["ការងារពេញម៉ោង"]`` (full-time).
    employment_types: list[str] = Field(default_factory=list)
    #: The contract text, e.g. "unlimited-term contract".
    contract_type_raw: str | None = Field(default=None)
    work_hours: str | None = Field(default=None)
    #: The board's Khmer education phrase, kept verbatim for the cleaner.
    education_raw: str | None = Field(default=None)
    #: The board's Khmer experience phrase, kept verbatim for the cleaner.
    experience_raw: str | None = Field(default=None)

    occupational_category: str | None = Field(default=None)
    industry: str | None = Field(default=None)

    salary_currency: str | None = Field(default="USD")
    salary_min: float | None = Field(default=None)
    salary_max: float | None = Field(default=None)
    #: Always ``monthly`` for this board, even when no amount is published.
    salary_period: str | None = Field(default="monthly")
    #: The verbatim salary text, e.g. ``$210 ~ $250 (ខែ)``.
    salary_text_raw: str | None = Field(default=None)

    vacancies_count: int | None = Field(default=None)

    job_url: str | None = Field(default=None)
    listing_category: str | None = Field(default=None)

    raw: dict[str, Any] = Field(default_factory=dict, description="Verbatim parsed fields.")

    @field_validator("title", "source_job_id", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    def posted_datetime(self) -> dt.datetime | None:
        if self.posted_date is None:
            return None
        return dt.datetime(self.posted_date.year, self.posted_date.month, self.posted_date.day)
